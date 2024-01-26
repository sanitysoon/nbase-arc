#
# Copyright 2015 Naver Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import unittest
import subprocess
import shlex
import os
import time
import Conf, Util, Cm, Pg, Pgs, Smr, Client, Log

class TestLogUtil (unittest.TestCase):

    def make_logs(self, pgs, log_count):
        clients = []
        num_clients = 2
        for i in range (0, num_clients):
            C = Client.Client()
            clients.append(C)
            C.slotid = i
            C.add(C.slotid, 'localhost', 1909)
            C.size(1024, C.slotid) # 1M
            C.tps(64000, C.slotid)

        for C in clients:
            C.start(C.slotid)

        checked_seqs = []
        while True:
            time.sleep(1)
            seqs = pgs.smr.getseq_log()
            max_seq = seqs['max']
            checked_seqs.append(max_seq)
            if max_seq / (64*1024*1024) >= log_count:
                break

        for C in clients:
            C.stop(C.slotid)
        return checked_seqs

    def test_copylog(self):
        src = None
        dst = None
        master = None
        try:
            src = Cm.CM("test_logcopy_src")
            src.create_workspace()
            pg = Pg.PG(0)

            master = Pgs.PGS(0, 'localhost', 1900, src.dir)
            pg.join(master, start=True)
            master.smr.wait_role(Smr.SMR.MASTER)


            # make some logs
            seqs = self.make_logs(master, 2)
            assert len(seqs) > 0, seqs

            # do copylog
            dst = Cm.CM("test_logcopy_dst")
            dst.create_workspace()

            prog = Conf.LOG_UTIL_BIN_PATH
            cmd = '%s copylog %s %s 0 %d' % (prog, master.dir, dst.dir, seqs[-1])
            popen = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            sout, serr = popen.communicate()
            assert (popen.returncode == 0), (sout, serr)

            # check files
            seq = 0
            to_seq = int(seqs[-1])
            while seq < to_seq:
                # e.g.) 0000000000000000100.log
                fn = "%019d.log" % seq
                sf = os.path.join(master.dir, fn)
                df = os.path.join(dst.dir, fn)

                if to_seq - seq > 64*1024*1024:
                    n = 64*1024*1024
                else:
                    n = to_seq - seq

                cmd = 'cmp -n %d %s %s' % (n, sf, df)
                popen = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                sout, serr = popen.communicate()
                assert (popen.returncode == 0), (sout, serr)

                # get log file name from seq
                seq = seq + 64*1024*1024
        finally:
            # Util.tstop('Check output!')
            if master is not None:
                master.kill_smr()
                master.kill_be()
            if src is not None:
                src.remove_workspace()
            if dst is not None:
                dst.remove_workspace()

    def test_logutil(self):
        cm = None
        master = None
        try:
            cm = Cm.CM("test_logutil")
            cm.create_workspace()
            pg = Pg.PG(0)

            # master --> master
            master = Pgs.PGS(0, 'localhost', 1900, cm.dir)
            pg.join(master, start=True)
            master.smr.wait_role(Smr.SMR.MASTER)

            # make some logs
            self.make_logs(master, 5)

            # Test raw dump option
            out, _ = Log.datadump_communicate(master.dir, 0, 5*1024, 'r')
            lines = out.split('\n')
            assert len(lines) > 0, len(lines)
            # error case
            out, err = Log.datadump_communicate(master.dir, 0, 5*1024, 'Tr')
            assert len(err) > 0 and err.startswith('-ERR'), err

            # get file sequences
            seqs = master.smr.getseq_log()
            file_seqs = []
            seq = 0
            while seq + 64*1024*1024 < seqs['max']:
                file_seqs.append(seq)
                seq = seq + 64*1024*1024

            # get leading timestamp and sequence from each logs and peek one
            peeks = []
            for seq in file_seqs:
                out, _ = Log.datadump_communicate(master.dir, seq, seq + 5*1024, 'Tsld32')
                lines = out.split('\n')
                assert len(lines) > 0
                peek = lines[len(lines)/2]
                peeks.append(peek)

            # find by time range and check peek is in the lines
            idx = 0
            for seq in file_seqs:
                peek = peeks[idx]
                ts = int(peek.split()[0])
                assert ts > 20160817000000000
                out, _ = Log.dumpbytime_communicate(master.dir, ts, ts+1, 'Tsld32')
                lines = out.split('\n')
                found = False
                for line in lines:
                    if line == peek:
                        found = True
                        break
                assert found == True
                idx = idx + 1

            # decachelog (just for coverage)
            out, _ = Log.decachelog_communicate(master.dir, file_seqs[-1], True)
            assert len(out) == 0

            # mincorelog (just for coverage)
            out, _ = Log.mincorelog_communicate(master.dir)
            assert len(out.split('\n')) >= 5

        finally:
            # Util.tstop('Check output!')
            if master is not None:
                master.kill_smr()
                master.kill_be()
            if cm is not None:
                cm.remove_workspace()

if __name__ == '__main__':
    unittest.main()
