# SIM-CITY webservice
#
# Copyright 2015 Joris Borgdorff <j.borgdorff@esciencecenter.nl>
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


import simcity
from picas.documents import Task
from numbers import Number
import multiprocessing as mp
import traceback


class Simulator(object):

    """
    SIM-CITY simulator
    """

    def __init__(self, ensemble, version, command, scoring, host, max_jobs=4,
                 polling_time=60, argnames=None, argprecisions=None,
                 couchdb=None, use_cache=False):
        self.couchdb = couchdb
        self.ensemble = ensemble
        self.version = version
        self.command = command
        self.scoring = scoring
        self.host = host
        self.max_jobs = max_jobs
        self.default_host = host
        self.polling_time = polling_time
        self.argnames = argnames
        self.argprecisions = argprecisions
        self.use_cache = use_cache
        self.current_pid = 0
        self.proc_q = mp.Queue()
        self.proc = {}

    def _keyval(self, p, i):
        try:
            key = self.argnames[i]
        except (TypeError, IndexError):
            key = str(i)

        try:
            value = p[i] - (p[i] % self.argprecisions[i])
        except (TypeError, IndexError):
            value = p[i]

        return (key, value)

    def __call__(self, p, host=None):
        if host is None:
            host = self.default_host

        kwargs = dict(self._keyval(p, i) for i in range(len(p)))

        task = None

        if self.use_cache:
            js_input = ""
            for key in kwargs:
                if isinstance(kwargs[key], Number):
                    js_input += "&& doc.input['%s'] == %f" % (key, kwargs[key])
                else:
                    js_input += "&& doc.input['%s'] == '%s'" % (
                        key, str(kwargs[key]))

            map_fun = '''function(doc) {
                if (doc.type == 'task' && doc.done > 0 &&
                    doc.command == '%s' && doc.version == '%s' %s) {
                    emit(doc._id, doc)
                }
            }''' % (self.command, self.version, js_input)
            for row in simcity.get_task_database().db.query(map_fun, limit=1):
                task = Task(row.value)
                print("using cache")

        if task is None:
            task, job = simcity.run_task({
                'command': self.command,
                'version': self.version,
                'input': kwargs,
                'ensemble': self.ensemble,
            }, self.host, self.max_jobs, polling_time=self.polling_time)

        if task.has_error():
            raise EnvironmentError('Simulation %s failed: %s'
                                   % (task.id, str(task.get_errors())))
        return self.scoring(task)

    def start(self, p, host=None):
        self.current_pid += 1
        self.proc[self.current_pid] = mp.Process(
            target=run_simulator, args=(self, self.current_pid, p, host,))
        self.proc[self.current_pid].start()
        return self.current_pid

    def join(self):
        pid, value = self.proc_q.get()
        self.proc[pid].join()
        del self.proc[pid]
        return (pid, value,)

    def has_result(self):
        return not self.proc_q.empty()

    def is_running(self):
        return len(self.proc) > 0 or self.has_result()


def run_simulator(simulator, pid, p, host):
    try:
        # reinitialize database connections in each thread
        simcity.init(simcity.get_config())
        value = simulator(p, host)
        simulator.proc_q.put((pid, value,))
    except Exception as ex:
        traceback.print_exc()
        simulator.proc_q.put((pid, ex,))
