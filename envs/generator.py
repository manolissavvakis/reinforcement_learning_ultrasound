import random
from envs.utils import copy_and_apply
import numpy as np


class PhantomGenerator:
    def __init__(self):
        pass

    def __next__(self):
        return self.get_next_phantom()

    def get_next_phantom(self):
        raise NotImplementedError


class ProbeGenerator:
    def __init__(self):
        pass

    def __next__(self):
        return self.get_next_probe()

    def get_next_probe(self):
        raise NotImplementedError


class ConstPhantomGenerator(PhantomGenerator):
    def __init__(self, phantom):
        super().__init__()
        self.phantom = phantom

    def get_next_phantom(self):
        return self.phantom


class ConstProbeGenerator(ProbeGenerator):
    def __init__(self, probe):
        super().__init__()
        self.probe = probe

    def get_next_probe(self):
        return self.probe

class RandomProbeGenerator(ProbeGenerator):
    def __init__(self, ref_probe, object_to_align, seed=None,
                 x_pos=None, y_pos=None, focal_pos=None, angle=None):
        super().__init__()
        self.ref_probe = ref_probe
        self.object_to_align = object_to_align
        if x_pos is None:
            self.x_pos = [i/1000 for i in range(-20, 30, 10)]
        else:
            self.x_pos = x_pos
        if y_pos is None:
            self.y_pos = [i/1000 for i in range(-20, 30, 10)]
        else:
            self.y_pos = y_pos
        if focal_pos is None:
            self.focal_pos = [i/1000 for i in range(10, 100, 10)]
        else:
            self.focal_pos = focal_pos
        if angle is None:
            self.angle = [self.object_to_align.angle]
        else:
            self.angle = angle
        self.rng = random.Random(seed)

    def get_next_probe(self):
        x = self.rng.choice(self.x_pos)
        y = self.rng.choice(self.y_pos)
        fd = self.rng.choice(self.focal_pos)
        a = self.rng.choice(self.angle)
        probe_pos = np.array([x, y, 0])
        return copy_and_apply(
            self.ref_probe, deep=True,
            pos=probe_pos,
            angle=a,
            focal_depth=fd
        )
