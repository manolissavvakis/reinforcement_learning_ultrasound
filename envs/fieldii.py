import subprocess
import tempfile
import glob
import os.path
import os
import numpy as np
import scipy.io
import shutil
import operator
import time
import atexit
from collections import namedtuple

_SCANLINES_DIR_SUFFIX = ".rf"
POINTS_MAT_VAR = "point_positions"
AMPS_MAT_VAR = "point_amplitudes"
SAMPL_FREQ_MAT_VAR = "fs"
RF_DATA_MAT_VAR = "rf_data"
TSTART_MAT_VAR = "tstart"


LinearArrayParams = namedtuple("LinearArrayParams", [
    # WARN: pickled
    "point_positions",
    "point_amplitudes",
    "no_lines",
    "z_focus",
    "image_width"
])

class Field2:
    """
    Field2: A class used to start Field2 sessions and
        generate data.
        
    :param working_dir: working directory for Field2 sessions.
    :param no_workers: number of workers for Field2 sessions.
    """
    def __init__(self, working_dir=None, no_workers=1):
        self._remove_working_dir = working_dir is None
        if working_dir is None:
            working_dir = tempfile.TemporaryDirectory(suffix='_fieldii')
        self.working_dir = working_dir
        self.no_workers = no_workers
        atexit.register(self._cleanup)
        self._start_sessions()

    def simulate_linear_array(
        self,
        point_positions, point_amplitudes, sampling_frequency,
        no_lines=50, z_focus=60/1000, image_width=40/1000
    ):
        """
        Create RF data.
        Create a .mat file which includes all the necessary data to generate
        the RF data. Then, go.* files are used as signals to begin the rf data
        scanlines generation process and ready.* files mean that scanlines are
        successfully generated. Merge the scanlines and delete .mat, go and ready
        files.
        
        :param point_positions: (n, 3) points used to generate the RF data.
        :param point_amplitudes: (n, 1) amplitudes of the points used.
        :param sampling_frequency: sampling frequency.
        :param no_lines: number of lines of RF data.
        :param z_focus: focal depth of the probe.
        :param image_width: number of columns of RF data.
        :return: RF data and a vector including start time of each
            scanline.
        """
        self._assert_workers_exists()
        input_file_path = os.path.join(self.working_dir.name, "input.mat")
        self._save_mat_file(
            filename=input_file_path,
            point_positions=point_positions,
            point_amplitudes=point_amplitudes,
            sampling_frequency=sampling_frequency,
            no_lines=no_lines,
            z_focus=z_focus,
            image_width=image_width
        )
        # Create "go files" n times.
        print("Simulating linear array in Field II...")
        for worker in range(self.no_workers):
            open(os.path.join(self.working_dir.name, ('go.%d' % worker)), 'a').close()
        # Wait till all matlab processes finish the job.
        ready_sign_pattern = os.path.join(self.working_dir.name, 'ready.*')
        i = 0
        while len(glob.glob(ready_sign_pattern)) != self.no_workers:
            time.sleep(1)
            if i % 10 == 0:
                self._assert_workers_exists()
            i = i+1
        # Output data is ready.
        (rf_array, t_start) = self._merge_scanlines(
            os.path.join(self.working_dir.name, "input.mat.rf"),
            sampling_frequency)
        # Cleanup.
        for worker in range(self.no_workers):
            go_file = os.path.join(self.working_dir.name, "go.%d" % worker)
            ready_file = os.path.join(self.working_dir.name, "ready.%d" % worker)
            if os.path.isfile(go_file):
                os.remove(go_file)
            if os.path.isfile(ready_file):
                os.remove(ready_file)
        os.remove(os.path.join(self.working_dir.name, "input.mat"))
        shutil.rmtree(os.path.join(self.working_dir.name, "input.mat.rf"))
        print("...simulation completed.")
        return rf_array, t_start

    def close(self):
        self._cleanup()

    def _save_mat_file(
        self,
        filename,
        point_positions,
        point_amplitudes,
        sampling_frequency,
        no_lines,
        z_focus,
        image_width
    ):
        scipy.io.savemat(
            filename, {
            POINTS_MAT_VAR: point_positions,
            AMPS_MAT_VAR: point_amplitudes,
            "no_lines": np.int32(no_lines),
            "z_focus": float(z_focus),
            "image_width": float(image_width)
        })

    def _start_sessions(self):
        """
        Start a Field2 session.
        """
        self._pipes = [self._start_session(worker) for worker in range(self.no_workers)]
        print("Started %d MATLAB worker(s)." % len(self._pipes))
        timeout = 120
        print("Waiting max. %d [s] till all MATLAB workers will be available..." % timeout)
        started_sign_pattern = os.path.join(self.working_dir.name, 'started.*')
        while len(glob.glob(started_sign_pattern)) != self.no_workers and timeout > 0:
            time.sleep(1)
            timeout -= 1
        if timeout <= 0:
             raise RuntimeError("Timeout waiting for MATLAB processes, stopping.")
        print("Checking state of workers...")
        self._assert_workers_exists()
        print("...OK!")

    def _start_session(self, session_id):
        """
        Initialize Field2 simulation.
        
        ..warning:
            Add Field2 to path unless it's added in matlab's path already.
            Also, in matlab_call, add matlab's path.
        """
        prev_dir = os.getcwd()
        os.chdir(os.path.dirname(__file__))
        fn_call = (
            "addpath('/home/spbtu/Manolis_Files/Field2'), " +
            "field_init, " +
            "try, " +
            ("simulate_linear_array(%d, \'%s\',\'%s\'), " % (session_id,
                                                             self.working_dir.name,
                                                             self.working_dir.name)) +
            "exit(0),"
            "catch ex, " +
            "fprintf('%s, %s \\n', ex.identifier, ex.message)," +
            "exit(1), " +
            "end ")
        matlab_call = ["/usr/local/MATLAB/R2018a/bin/matlab", "-nosplash", "-nodesktop", "-r", fn_call]
        pipe = subprocess.Popen(matlab_call)
        os.chdir(prev_dir)
        return pipe

    def _assert_workers_exists(self):
        """
        Check if there are any workers left.
        """
        for worker in range(self.no_workers):
            if self._pipes[worker].poll() is not None:
                raise RuntimeError("Worker %d is dead! Check logs, why he has been stopped." % worker)

    def _merge_scanlines(self, scanline_dir, sampling_frequency):
        ln_path = glob.glob(os.path.join(scanline_dir, "ln*.mat"))
        mats = (scipy.io.loadmat(line_file) for line_file in ln_path)

        data = [(mat[RF_DATA_MAT_VAR].flatten(), mat[TSTART_MAT_VAR][0][0], mat['i'][0][0])
                for mat in mats]
        data.sort(key=operator.itemgetter(2))
        
        # Make all scanlines start from t=0.
        # We pad the scanlines from the left with zeros (because we don't know
        # what values should be between t=0 and t=tstart).
        def pad_scanline_from_t_0(scanline, tstart):
            # we want to start from sample close to t=0
            idx = np.round(tstart*sampling_frequency).astype(int)
            if idx <= 0:
                return scanline[-(idx):]
            return np.concatenate((np.zeros(idx), scanline))
        left_padded_data = [(pad_scanline_from_t_0(scanline, tstart), tstart)
                            for (scanline, tstart, _) in data]
        t_start_vector = np.array([tstart for (_, tstart) in left_padded_data])
        # make all scanlines the same size
        scanline_max_length = max((scanline.shape[0] for (scanline, _) in left_padded_data))
        right_padded_data = (np.concatenate((scanline, np.zeros(scanline_max_length-scanline.shape[0])))
                             for scanline, _ in  left_padded_data)
        columns = [scanline.reshape((-1, 1)) for scanline in right_padded_data]
        rf_array = np.concatenate(columns, axis=1)
        return (rf_array, t_start_vector)

    def _cleanup(self):
        """
        Clear Field2 sessions.
        """
        for worker in range(self.no_workers):
            open(os.path.join(self.working_dir.name, ('die.%d' % worker)), 'a').close()
        print("Waiting till all child processes die...")
        for pipe in self._pipes:
            while pipe.poll() is None:
                time.sleep(2)
        print("All subprocesses are dead now, session is closed.")
