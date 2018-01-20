#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import logging

from tornado.ioloop import IOLoop
# from lxml.html.diff import htmldiff
from apscheduler.schedulers.tornado import TornadoScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

import tornado.httpserver
import tornado.ioloop
import tornado.options
from tornado.options import define, options
import tornado.web
from tornado import gen, escape

CONF_DIR = ''
JOBS_STORE = 'sqlite:///conf/jobs.db'
API_VERSION = '1.0'
SCHEDULES_FILE = 'conf/schedules.json'

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def read_schedules():
    if not os.path.isfile(SCHEDULES_FILE):
        return {'schedules': {}}
    try:
        with open(SCHEDULES_FILE, 'r') as fd:
            return json.loads(fd.read())
    except Exception as e:
        logger.error('unable to read %s: %s' % (SCHEDULES_FILE, e))
        return {'schedules': {}}


def write_schedules(schedules):
    with open(SCHEDULES_FILE, 'w') as fd:
        fd.write(json.dumps(schedules, indent=2))


def next_id(schedules):
    ids = schedules.get('schedules', {}).keys()
    if not ids:
        return '1'
    return str(max([int(i) for i in ids]) + 1)


def get_schedule(id_):
    schedules = read_schedules()
    data = schedules.get('schedules', {}).get(id_, {})
    data['id'] = str(id_)
    return data


class DiffidoBaseException(Exception):
    """Base class for diffido custom exceptions.

    :param message: text message
    :type message: str
    :param status: numeric http status code
    :type status: int"""
    def __init__(self, message, status=400):
        super(DiffidoBaseException, self).__init__(message)
        self.message = message
        self.status = status


class BaseHandler(tornado.web.RequestHandler):
    """Base class for request handlers."""
    # Cache currently connected users.
    _users_cache = {}

    # set of documents we're managing (a collection in MongoDB or a table in a SQL database)
    document = None
    collection = None

    # A property to access the first value of each argument.
    arguments = property(lambda self: dict([(k, v[0].decode('utf-8'))
                                            for k, v in self.request.arguments.items()]))

    @property
    def clean_body(self):
        """Return a clean dictionary from a JSON body, suitable for a query on MongoDB.

        :returns: a clean copy of the body arguments
        :rtype: dict"""
        return escape.json_decode(self.request.body or '{}')

    def write_error(self, status_code, **kwargs):
        """Default error handler."""
        if isinstance(kwargs.get('exc_info', (None, None))[1], DiffidoBaseException):
            exc = kwargs['exc_info'][1]
            status_code = exc.status
            message = exc.message
        else:
            message = 'internal error'
        self.build_error(message, status=status_code)

    def is_api(self):
        """Return True if the path is from an API call."""
        return self.request.path.startswith('/v%s' % API_VERSION)

    def initialize(self, **kwargs):
        """Add every passed (key, value) as attributes of the instance."""
        for key, value in kwargs.items():
            setattr(self, key, value)

    def build_error(self, message='', status=400):
        """Build and write an error message.

        :param message: textual message
        :type message: str
        :param status: HTTP status code
        :type status: int
        """
        self.set_status(status)
        self.write({'error': True, 'message': message})

    def build_success(self, message='', status=200):
        """Build and write a success message.

        :param message: textual message
        :type message: str
        :param status: HTTP status code
        :type status: int
        """
        self.set_status(status)
        self.write({'error': False, 'message': message})


class SchedulesHandler(BaseHandler):
    @gen.coroutine
    def get(self, id_=None, *args, **kwargs):
        if id_ is not None:
            self.write({'schedule': get_schedule(id_)})
            return
        schedules = read_schedules()
        self.write(schedules)

    @gen.coroutine
    def put(self, id_=None, *args, **kwargs):
        if id_ is None:
            return self.build_error(message='update action requires an ID')
        data = self.clean_body
        schedules = read_schedules()
        if id_ not in schedules.get('schedules', {}):
            return self.build_error(message='schedule %s not found' % id_)
        schedules['schedules'][id_] = data
        write_schedules(schedules)
        self.write(get_schedule(id_=id_))

    @gen.coroutine
    def post(self, *args, **kwargs):
        data = self.clean_body
        schedules = read_schedules()
        id_ = next_id(schedules)
        schedules['schedules'][id_] = data
        write_schedules(schedules)
        self.write(get_schedule(id_=id_))

    @gen.coroutine
    def delete(self, id_=None, *args, **kwargs):
        if id_ is None:
            return self.build_error(message='an ID must be specified')
        schedules = read_schedules()
        if id_ in schedules.get('schedules', {}):
            del schedules['schedules'][id_]
            write_schedules(schedules)
        self.build_success(message='removed schedule %s' % id_)


class TemplateHandler(BaseHandler):
    """Handler for the / path."""
    app_path = os.path.join(os.path.dirname(__file__), "dist")

    @gen.coroutine
    def get(self, *args, **kwargs):
        page = 'index.html'
        if args and args[0]:
            page = args[0].strip('/')
        arguments = self.arguments
        self.render(page, **arguments)


def run_scheduled(id_=None, *args, **kwargs):
    print('RUNNING %d' % id_)

def run():
    print('runno!')

def serve():
    jobstores = {'default': SQLAlchemyJobStore(url=JOBS_STORE)}
    scheduler = TornadoScheduler(jobstores=jobstores)
    scheduler.start()
    #scheduler.remove_job('run')
    #scheduler.add_job(run, 'interval', minutes=1)

    define('port', default=3210, help='run on the given port', type=int)
    define('address', default='', help='bind the server at the given address', type=str)
    define('ssl_cert', default=os.path.join(os.path.dirname(__file__), 'ssl', 'diffido_cert.pem'),
            help='specify the SSL certificate to use for secure connections')
    define('ssl_key', default=os.path.join(os.path.dirname(__file__), 'ssl', 'diffido_key.pem'),
            help='specify the SSL private key to use for secure connections')
    define('debug', default=False, help='run in debug mode')
    define('config', help='read configuration file',
            callback=lambda path: tornado.options.parse_config_file(path, final=False))
    tornado.options.parse_command_line()

    if options.debug:
        logger.setLevel(logging.DEBUG)

    ssl_options = {}
    if os.path.isfile(options.ssl_key) and os.path.isfile(options.ssl_cert):
        ssl_options = dict(certfile=options.ssl_cert, keyfile=options.ssl_key)

    init_params = dict(listen_port=options.port, logger=logger, ssl_options=ssl_options,
                       scheduler=scheduler)

    _schedules_path = r'schedules/?(?P<id_>\d+)?'
    application = tornado.web.Application([
            ('/api/%s' % _schedules_path, SchedulesHandler, init_params),
            (r'/api/v%s/%s' % (API_VERSION, _schedules_path), SchedulesHandler, init_params),
            (r'/?(.*)', TemplateHandler, init_params),
        ],
        static_path=os.path.join(os.path.dirname(__file__), 'dist/static'),
        template_path=os.path.join(os.path.dirname(__file__), 'dist/'),
        debug=options.debug)
    http_server = tornado.httpserver.HTTPServer(application, ssl_options=ssl_options or None)
    logger.info('Start serving on %s://%s:%d', 'https' if ssl_options else 'http',
                                                 options.address if options.address else '127.0.0.1',
                                                 options.port)
    http_server.listen(options.port, options.address)

    try:
        IOLoop.instance().start()
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == '__main__':
    serve()
