import collections
import celery
import celery.states
import threading
import prometheus_client
import argparse


DEFAULT_BROKER='redis://redis:6379/0'
DEFAULT_ADDR='0.0.0.0:8888'

TASKS = prometheus_client.Gauge('celery_tasks', 'Number of tasks per state', ['state'])
WORKERS = prometheus_client.Gauge('celery_workers', 'Number of alive workers')


class MonitorThread(threading.Thread):
    """
    MonitorThread is the thread that will collect the data that is later exposed
    from Celery using its eventing system.
    """
    def run(self):
        app = celery.Celery(broker="redis://redis:6379/0")
        self._state = app.events.State()
        self._known_states = set()
        self._monitor(app)

    def _process_event(self, evt):
        self._state.clear()
        self._state.event(evt)
        cnt = collections.Counter(t.state for _, t in self._state.tasks.items())
        self._known_states.update(cnt.elements())
        seen_states = set()
        for state_name, count in cnt.items():
            TASKS.labels(state_name).set(count)
            seen_states.add(state_name)
        for state_name in self._known_states - seen_states:
            TASKS.labels(state_name).set(0)
        WORKERS.set(len(self._state.alive_workers()))

    def _monitor(self, app):
        while True:
            with app.connection() as conn:
                recv = app.events.Receiver(conn, handlers={
                    '*': self._process_event
                })
                recv.capture(limit=None, timeout=None, wakeup=True)


def setup_metrics():
    """
    This initializes the available metrics with default values so that
    even before the first event is received, data can be exposed.
    """
    for state in celery.states.ALL_STATES:
        TASKS.labels(state).set(0)
    WORKERS.set(0)


def start_httpd(addr):
    """
    Starts the exposing HTTPD using the addr provided in a seperate
    thread.
    """
    host, port = addr.split(':')
    print('Starting HTTPD on {}:{}'.format(host, port))
    prometheus_client.start_http_server(int(port), host)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--broker', dest='broker', default=DEFAULT_BROKER,
        help="URL to the Celery broker. Defaults to {}".format(DEFAULT_BROKER))
    parser.add_argument(
        '--addr', dest='addr', default=DEFAULT_ADDR,
        help="Address the HTTPD should listen on. Defaults to {}".format(DEFAULT_ADDR))
    opts = parser.parse_args()

    setup_metrics()
    t = MonitorThread()
    t.start()
    start_httpd(opts.addr)
    t.join()


if __name__ == '__main__':
    main()
