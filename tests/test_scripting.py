from collections import deque
import unittest


class Test_get_root(unittest.TestCase):
    def _callFUT(self, app, request=None):
        from pyramid.scripting import get_root

        return get_root(app, request)

    def _makeRegistry(self):
        return DummyRegistry([DummyFactory])

    def setUp(self):
        from pyramid.threadlocal import manager

        self.manager = manager
        self.default = manager.get()

    def test_it_norequest(self):
        registry = self._makeRegistry()
        app = DummyApp(registry=registry)
        root, closer = self._callFUT(app)
        self.assertEqual(dummy_root, root)
        pushed = self.manager.get()
        self.assertEqual(pushed['registry'], registry)
        self.assertEqual(pushed['request'].registry, registry)
        self.assertEqual(pushed['request'].environ['path'], '/')
        closer()
        self.assertEqual(self.default, self.manager.get())

    def test_it_withrequest(self):
        registry = self._makeRegistry()
        app = DummyApp(registry=registry)
        request = DummyRequest({})
        root, closer = self._callFUT(app, request)
        self.assertEqual(dummy_root, root)
        pushed = self.manager.get()
        self.assertEqual(pushed['registry'], registry)
        self.assertEqual(pushed['request'], request)
        self.assertEqual(pushed['request'].registry, registry)
        closer()
        self.assertEqual(self.default, self.manager.get())


class Test_prepare(unittest.TestCase):
    def _callFUT(self, request=None, registry=None):
        from pyramid.scripting import prepare

        return prepare(request, registry)

    def _makeRegistry(self, L=None):
        if L is None:
            L = [None, DummyFactory]
        return DummyRegistry(L)

    def setUp(self):
        from pyramid.threadlocal import manager

        self.manager = manager
        self.default = manager.get()

    def test_it_no_valid_apps(self):
        from pyramid.exceptions import ConfigurationError

        self.assertRaises(ConfigurationError, self._callFUT)

    def test_it_norequest(self):
        registry = self._makeRegistry([DummyFactory, None, DummyFactory])
        info = self._callFUT(registry=registry)
        root, closer, request = info['root'], info['closer'], info['request']
        pushed = self.manager.get()
        self.assertEqual(pushed['registry'], registry)
        self.assertEqual(pushed['request'].registry, registry)
        self.assertEqual(root.a, (pushed['request'],))
        closer()
        self.assertEqual(self.default, self.manager.get())
        self.assertEqual(request.context, root)

    def test_it_withrequest_hasregistry(self):
        request = DummyRequest({})
        registry = request.registry = self._makeRegistry()
        info = self._callFUT(request=request)
        root, closer, request = info['root'], info['closer'], info['request']
        pushed = self.manager.get()
        self.assertEqual(pushed['request'], request)
        self.assertEqual(pushed['registry'], registry)
        self.assertEqual(pushed['request'].registry, registry)
        self.assertEqual(root.a, (request,))
        closer()
        self.assertEqual(self.default, self.manager.get())
        self.assertEqual(request.context, root)
        self.assertEqual(request.registry, registry)

    def test_it_withrequest_noregistry(self):
        request = DummyRequest({})
        registry = self._makeRegistry()
        info = self._callFUT(request=request, registry=registry)
        root, closer, request = info['root'], info['closer'], info['request']
        closer()
        self.assertEqual(request.context, root)
        # should be set by prepare
        self.assertEqual(request.registry, registry)

    def test_it_with_request_and_registry(self):
        request = DummyRequest({})
        registry = request.registry = self._makeRegistry()
        info = self._callFUT(request=request, registry=registry)
        root, closer, root = info['root'], info['closer'], info['root']
        pushed = self.manager.get()
        self.assertEqual(pushed['request'], request)
        self.assertEqual(pushed['registry'], registry)
        self.assertEqual(pushed['request'].registry, registry)
        self.assertEqual(root.a, (request,))
        closer()
        self.assertEqual(self.default, self.manager.get())
        self.assertEqual(request.context, root)

    def test_it_with_request_context_already_set(self):
        request = DummyRequest({})
        context = Dummy()
        request.context = context
        registry = request.registry = self._makeRegistry()
        info = self._callFUT(request=request, registry=registry)
        closer = info['closer']
        closer()
        self.assertEqual(request.context, context)

    def test_it_with_extensions(self):
        from pyramid.util import InstancePropertyHelper

        exts = DummyExtensions()
        ext_method = lambda r: 'bar'
        name, fn = InstancePropertyHelper.make_property(ext_method, 'foo')
        exts.descriptors[name] = fn
        request = DummyRequest({})
        registry = request.registry = self._makeRegistry([exts, DummyFactory])
        info = self._callFUT(request=request, registry=registry)
        self.assertEqual(request.foo, 'bar')
        closer = info['closer']
        closer()

    def test_it_is_a_context_manager(self):
        request = DummyRequest({})
        registry = request.registry = self._makeRegistry()
        closer_called = [False]
        with self._callFUT(request=request) as info:
            root, request = info['root'], info['request']
            pushed = self.manager.get()
            self.assertEqual(pushed['request'], request)
            self.assertEqual(pushed['registry'], registry)
            self.assertEqual(pushed['request'].registry, registry)
            self.assertEqual(root.a, (request,))
            orig_closer = info['closer']

            def closer():
                orig_closer()
                closer_called[0] = True

            info['closer'] = closer
        self.assertTrue(closer_called[0])
        self.assertEqual(self.default, self.manager.get())
        self.assertEqual(request.context, root)
        self.assertEqual(request.registry, registry)

    def test_closer_invokes_finished_callbacks(self):
        finish_called = [False]

        def finished_callback(request):
            finish_called[0] = True

        request = DummyRequest({})
        request.registry = self._makeRegistry()
        info = self._callFUT(request=request)
        request.add_finished_callback(finished_callback)
        closer = info['closer']
        closer()
        self.assertTrue(finish_called[0])


class Test__make_request(unittest.TestCase):
    def _callFUT(self, path='/', registry=None):
        from pyramid.scripting import _make_request

        return _make_request(path, registry)

    def _makeRegistry(self):
        return DummyRegistry([DummyFactory])

    def test_it_with_registry(self):
        registry = self._makeRegistry()
        request = self._callFUT('/', registry)
        self.assertEqual(request.environ['path'], '/')
        self.assertEqual(request.registry, registry)

    def test_it_with_no_registry(self):
        from pyramid.config import global_registries

        registry = self._makeRegistry()
        global_registries.add(registry)
        try:
            request = self._callFUT('/hello')
            self.assertEqual(request.environ['path'], '/hello')
            self.assertEqual(request.registry, registry)
        finally:
            global_registries.empty()


class TestRequestExtensionGenerations(unittest.TestCase):
    """Same-process, same-registry timing between scripting environments
    and router inbound requests."""

    def setUp(self):
        from pyramid.config import Configurator
        from pyramid.router import Router
        from pyramid.threadlocal import manager

        self.manager = manager
        self.default = manager.get()
        self._envs = []
        self.config = Configurator(settings=self._settings())
        self.config.add_request_method(lambda r: 'gen1', name='ext_method')
        self.config.add_request_method(
            lambda r: object(), name='ext_prop', property=True
        )
        self.config.add_request_method(
            lambda r: object(), name='ext_reified', reify=True
        )
        self.config.commit()
        self.registry = self.config.registry
        # the router is built at generation 1 and never rebuilt
        self.router = Router(self.registry)

    def tearDown(self):
        while self._envs:
            env = self._envs.pop()
            try:
                env['closer']()
            except Exception:
                pass
        self.assertEqual(self.default, self.manager.get())

    def _settings(self):
        return {'debug_notfound': False, 'debug_routematch': False}

    def _prepare(self, request=None):
        from pyramid.scripting import prepare

        env = prepare(request=request, registry=self.registry)
        self._envs.append(env)
        return env

    def _close(self, env):
        env['closer']()
        self._envs.remove(env)

    def _commit_generation_two(self, name='ext_later', value='gen2'):
        from pyramid.interfaces import IRequestExtensions

        exts = self.registry.getUtility(IRequestExtensions)
        self.assertEqual(exts.epoch, 3)
        self.config.add_request_method(lambda r: value, name=name)
        self.config.commit()
        self.assertEqual(exts.epoch, 4)
        return exts

    def test_method_property_reify_differences_on_prepare(self):
        env = self._prepare()
        request = env['request']
        # plain method is callable and receives the request
        self.assertEqual(request.ext_method(), 'gen1')
        # plain property recomputes on every read
        self.assertIsNot(request.ext_prop, request.ext_prop)
        # reify caches the computed object for the request lifetime
        self.assertIs(request.ext_reified, request.ext_reified)
        self._close(env)

    def test_prepare_mounts_extensions_get_root_does_not(self):
        from pyramid.scripting import get_root
        from pyramid.threadlocal import get_current_request

        env = self._prepare()
        self.assertTrue(hasattr(env['request'], 'ext_method'))
        self._close(env)

        root, closer = get_root(self.router)
        request = get_current_request()
        self.assertFalse(hasattr(request, 'ext_method'))
        self.assertFalse(hasattr(request, 'ext_reified'))
        closer()

    def test_prepare_closer_runs_finished_get_root_closer_does_not(self):
        from pyramid.scripting import get_root
        from pyramid.threadlocal import get_current_request

        events = []
        env = self._prepare()
        env['request'].add_finished_callback(
            lambda r: events.append('prepare')
        )
        self._close(env)
        self.assertEqual(events, ['prepare'])

        root, closer = get_root(self.router)
        request = get_current_request()
        request.add_finished_callback(lambda r: events.append('get_root'))
        closer()
        # the get_root closer only ends the context
        self.assertEqual(events, ['prepare'])

    def test_nested_prepare_isolates_callbacks_and_current_request(self):
        from pyramid.threadlocal import get_current_request

        events = []
        outer = self._prepare()
        outer['request'].add_finished_callback(
            lambda r: events.append(('outer', r is outer['request']))
        )

        inner = self._prepare()
        self.assertIs(get_current_request(), inner['request'])
        self.assertIsNot(inner['request'], outer['request'])
        inner['request'].add_finished_callback(
            lambda r: events.append(('inner', r is inner['request']))
        )

        self._close(inner)
        # the inner closer settles only the inner request's callbacks
        self.assertEqual(events, [('inner', True)])
        # the outer environment is exactly restored
        self.assertIs(get_current_request(), outer['request'])

        self._close(outer)
        self.assertEqual(events, [('inner', True), ('outer', True)])
        self.assertIsNone(get_current_request())

    def test_nested_prepare_same_request_never_drains_outer_callbacks(self):
        from pyramid.threadlocal import get_current_request

        events = []
        outer = self._prepare()
        request = outer['request']
        request.add_finished_callback(lambda r: events.append('outer'))

        inner = self._prepare(request=request)
        request.add_finished_callback(lambda r: events.append('inner'))

        self._close(inner)
        self.assertEqual(events, ['inner'])
        self.assertIs(get_current_request(), request)

        self._close(outer)
        self.assertEqual(events, ['inner', 'outer'])
        self.assertIsNone(get_current_request())

    def test_nested_get_root_restores_outer_prepare_view(self):
        from pyramid.scripting import get_root
        from pyramid.threadlocal import get_current_request

        outer = self._prepare()
        outer_request = outer['request']

        root, closer = get_root(self.router)
        inner_request = get_current_request()
        self.assertIsNot(inner_request, outer_request)
        # get_root never mounts request extensions
        self.assertFalse(hasattr(inner_request, 'ext_method'))
        closer()

        self.assertIs(get_current_request(), outer_request)
        self.assertEqual(get_current_request().ext_method(), 'gen1')
        self._close(outer)

    def test_new_generation_pins_old_request_new_prepare_sees_new(self):
        env1 = self._prepare()
        old_request = env1['request']
        self.assertFalse(hasattr(old_request, 'ext_later'))

        self._commit_generation_two()

        # the already prepared request keeps its old generation view
        self.assertFalse(hasattr(old_request, 'ext_later'))

        env2 = self._prepare()
        new_request = env2['request']
        self.assertEqual(new_request.ext_later(), 'gen2')
        # previous generation extensions remain visible
        self.assertEqual(new_request.ext_method(), 'gen1')
        self.assertIs(new_request.ext_reified, new_request.ext_reified)
        self._close(env2)
        self._close(env1)

    def test_new_generation_visible_to_router_inbound(self):
        from pyramid.httpexceptions import HTTPNotFound
        from pyramid.request import Request

        self._commit_generation_two()

        environ = Request.blank('/').environ
        with self.router.request_context(environ) as request:
            self.assertEqual(request.ext_method(), 'gen1')
            self.assertEqual(request.ext_later(), 'gen2')

        subrequest = Request.blank('/')
        self.assertRaises(
            HTTPNotFound,
            self.router.invoke_subrequest,
            subrequest,
            use_tweens=False,
        )
        # the subrequest ingress path shares the same registration
        self.assertEqual(subrequest.ext_method(), 'gen1')
        self.assertEqual(subrequest.ext_later(), 'gen2')

    def test_router_built_before_extensions_sees_later_ingress(self):
        from pyramid.config import Configurator
        from pyramid.request import Request
        from pyramid.router import Router

        config = Configurator(settings=self._settings())
        router = Router(config.registry)  # no extensions registered yet
        config.add_request_method(lambda r: 'late', name='ext_late')
        config.commit()
        with router.request_context(Request.blank('/').environ) as request:
            self.assertEqual(request.ext_late(), 'late')

    def test_request_local_cache_generation_boundary(self):
        from pyramid.request import RequestLocalCache

        calls = []
        cache = RequestLocalCache()

        def load(request):
            calls.append(1)
            return object()

        outer = self._prepare()
        request = outer['request']
        first = cache.get_or_create(request, load)
        self.assertIs(cache.get_or_create(request, load), first)
        self.assertEqual(len(calls), 1)

        self._commit_generation_two()

        inner = self._prepare(request=request)
        # the request crossed into the new generation during nested prepare
        second = cache.get_or_create(request, load)
        self.assertIsNot(second, first)
        self.assertEqual(request.ext_later(), 'gen2')
        self.assertIs(cache.get_or_create(request, load), second)

        self._close(inner)
        self._close(outer)

    def test_request_local_cache_isolates_prepared_generations(self):
        from pyramid.request import RequestLocalCache

        cache = RequestLocalCache()
        marker = []

        def load(request):
            marker.append(1)
            return len(marker)

        self._commit_generation_two()
        env1 = self._prepare()
        env2 = self._prepare()
        self.assertEqual(cache.get_or_create(env1['request'], load), 1)
        self.assertEqual(cache.get_or_create(env2['request'], load), 2)
        self.assertEqual(cache.get_or_create(env1['request'], load), 1)
        self.assertEqual(cache.get_or_create(env2['request'], load), 2)
        self._close(env2)
        self._close(env1)


class Dummy:
    pass


dummy_root = Dummy()


class DummyFactory:
    @classmethod
    def blank(cls, path):
        req = DummyRequest({'path': path})
        return req

    def __init__(self, *a, **kw):
        self.a = a
        self.kw = kw


class DummyRegistry:
    def __init__(self, utilities):
        self.utilities = utilities

    def queryUtility(self, iface, default=None):  # pragma: no cover
        if self.utilities:
            return self.utilities.pop(0)
        return default


class DummyApp:
    def __init__(self, registry=None):
        if registry:
            self.registry = registry

    def root_factory(self, environ):
        return dummy_root


class DummyRequest:
    matchdict = None
    matched_route = None

    def __init__(self, environ):
        self.environ = environ
        self.finished_callbacks = deque()

    def add_finished_callback(self, cb):
        self.finished_callbacks.append(cb)

    def _process_finished_callbacks(self):
        while self.finished_callbacks:
            cb = self.finished_callbacks.popleft()
            cb(self)


class DummyExtensions:
    def __init__(self):
        self.descriptors = {}
        self.methods = {}
