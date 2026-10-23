# Enfriamiento monotónico entre sesiones privadas de Microsoft.
import math, time
class Cooldown:
    def __init__(self,seconds=30,clock=None):
        self.seconds=float(seconds)
        self.clock=clock or time.monotonic
        self.deadline=0.0
    def begin(self):
        self.deadline=max(self.deadline,self.clock()+self.seconds)
    def remaining(self):
        return max(0,math.ceil(self.deadline-self.clock()))
