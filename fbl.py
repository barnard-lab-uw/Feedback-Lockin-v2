'''A multi-terminal lockin amplifier with feedback.

Its intended function is to allow for sourcing of current to contacts of a
multi-terminal device while simultaneously holding contacts at fixed
potentials. In particular, it can act to set virtual grounds in the device and
record the current passing into or out of each channel.
'''
from PySide2.QtCore import *
import numpy as np

from sin_outs import SinOutputs
from lockin_calc import LockinCalculator
from moving_averager import MovingAverager
from discrete_pi import DiscretePI
from bias_resistor import BiasResistor


_MIN_OUT = -10.0
_MAX_OUT = 10.0


class FeedbackLockin(QObject):
    def __init__(self, channels, points):
        QObject.__init__(self)
        self._channels = channels

        self._control_pi = DiscretePI()
        self._lockin = LockinCalculator(points)
        self._bias_r = BiasResistor(channels)
        self._sines = SinOutputs(channels, points)

        # Average both the amplitudes as well as the raw input data.
        self._amp_averager = MovingAverager()
        self._series_averager = MovingAverager()

        self.vOuts = np.zeros(channels)
        self.vIns = np.zeros(channels)
        self.ACins = np.zeros(channels)
        self.Phaseins = np.zeros(channels)
        self._feedback_on = np.zeros(channels, dtype=bool)
        self._control_pi.setNparams(channels)

    def update_amps(self, val, chan):
        self._sines.setSingleAmp(val, chan)
        self.vOuts[chan] = val

    def update_averaging(self, averaging):
        self._amp_averager.set_averaging(averaging)
        self._series_averager.set_averaging(averaging)

    def update_setpoint(self, val, chan):
        self._control_pi.updateSingleSetpoint(val, chan)
        self.vIns[chan] = val

    def update_k(self, Kint, Kprop):
        self._control_pi.setKint(Kint)
        self._control_pi.setKprop(Kprop)

    def set_feedback_enabled(self, chan, enabled):
        self._feedback_on[chan] = enabled
        self._bias_r.setZeroSumDisabledAxes(0.5, ~self._feedback_on)
        self._control_pi.zeroErrors(self._bias_r.reverse())
        self._control_pi.set_output_enabled(chan, enabled)

    def set_reference(self, chan):
        # Sets the index of the channel being used as a reference.
        # If <0 the reference value is zero.
        self._control_pi.setReferenceIdx(chan)

    def sine_out(self):
        out = self._sines.output()
        np.clip(out, _MIN_OUT, _MAX_OUT, out)
        return out

    def autotune_pid(self, scaleFactor):
        if np.max(np.abs(self.vOuts)) > .001:
            ampsRatio = (scaleFactor * np.max(np.abs(self.vOuts))
                / np.max(np.abs(self.vIns)))
            self._control_pi.setKint(ampsRatio)
        return ampsRatio

    def read_in(self, data):
        calcedAmps = self._lockin.calc_amps(data)
        self.data = self._series_averager.step(data)
        avged = self._amp_averager.step(calcedAmps)
        X = avged[0]
        Y = avged[1]
        self.X = X
        self.Y = Y
        self.R = np.sqrt(X*X + Y*Y)
        self.P = np.degrees(np.arctan2(Y, X))

        # Setpoint amplitudes calculated. Note that we feedback on the
        # unaveraged results.
        ampsSetOut = self._control_pi.step(calcedAmps[0])

        # If no feedback, force output to its original value.
        for i in range(self._channels):
            if not self._feedback_on[i]:
                ampsSetOut[i] = self.vOuts[i]

        # Transform to maintain current conservation.
        ampsSetOut = self._bias_r.step(ampsSetOut)

        # Updates the output sinewaves.
        self._sines.setAmps(ampsSetOut)

        for i in range(self._channels):
            if self._feedback_on[i]:
                self.vOuts[i] = ampsSetOut[i]
