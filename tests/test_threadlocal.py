import unittest

from pyramid import testing


class TestThreadLocalManager(unittest.TestCase):
    def setUp(self):
        testing.setUp()

    def tearDown(self):
        testing.tearDown()

    def _getTargetClass(self):
        from pyramid.threadlocal import ThreadLocalManager

        return ThreadLocalManager

    def _makeOne(self, default=lambda *x: 1):
        return self._getTargetClass()(default)

    def test_init(self):
        local = self._makeOne()
        self.assertEqual(local.stack, [])
        self.assertEqual(local.get(), 1)

    def test_default(self):
        def thedefault():
            return '123'

        local = self._makeOne(thedefault)
        self.assertEqual(local.stack, [])
        self.assertEqual(local.get(), '123')

    def test_push_and_pop(self):
        local = self._makeOne()
        local.push(True)
        self.assertEqual(local.get(), True)
        self.assertEqual(local.pop(), True)
        self.assertEqual(local.pop(), None)
        self.assertEqual(local.get(), 1)

    def test_set_get_and_clear(self):
        local = self._makeOne()
        local.set(None)
        self.assertEqual(local.stack, [None])
        self.assertEqual(local.get(), None)
        local.clear()
        self.assertEqual(local.get(), 1)
        local.clear()
        self.assertEqual(local.get(), 1)


class TestGetCurrentRequest(unittest.TestCase):
    def _callFUT(self):
        from pyramid.threadlocal import get_current_request

        return get_current_request()

    def test_it_None(self):
        request = self._callFUT()
        self.assertEqual(request, None)

    def test_it(self):
        from pyramid.threadlocal import manager

        request = object()
        try:
            manager.push({'request': request})
            self.assertEqual(self._callFUT(), request)
        finally:
            manager.pop()
        self.assertEqual(self._callFUT(), None)


class TestRequestContext(unittest.TestCase):
    def _getTargetClass(self):
        from pyramid.threadlocal import RequestContext

        return RequestContext

    def _makeOne(self, request=None):
        if request is None:
            request = DummyRequest()
        return self._getTargetClass()(request)

    def test_epoch_follows_pinned_generation(self):
        from pyramid.util import REQUEST_EXTENSIONS_EPOCH

        request = DummyRequest()
        ctx = self._makeOne(request)
        # nothing applied to the request yet (e.g. a get_root request)
        self.assertIsNone(ctx.epoch)
        setattr(request, REQUEST_EXTENSIONS_EPOCH, 4)
        self.assertEqual(ctx.epoch, 4)

    def test_begin_and_end_are_generation_boundaries(self):
        from pyramid.threadlocal import get_current_registry, get_current_request

        outer_request = DummyRequest()
        outer = self._makeOne(outer_request)
        outer.begin()
        self.assertIs(get_current_request(), outer_request)

        inner_request = DummyRequest()
        inner = self._makeOne(inner_request)
        inner.begin()
        self.assertIs(get_current_request(), inner_request)

        # ending the inner boundary restores the outer current request
        inner.end()
        self.assertIs(get_current_request(), outer_request)
        self.assertIs(get_current_registry(), outer_request.registry)
        outer.end()
        self.assertIsNone(get_current_request())

    def test_end_is_idempotent(self):
        ctx = self._makeOne()
        ctx.begin()
        ctx.end()
        ctx.end()  # must not pop a frame belonging to another context

    def test_end_unwinds_to_its_own_frame(self):
        from pyramid.threadlocal import manager

        outer_request = DummyRequest()
        outer = self._makeOne(outer_request)
        outer.begin()
        # a stray frame pushed on top of the outer boundary
        manager.push({'registry': object(), 'request': object()})
        # ending the outer context must not leave the current request
        # pointing at the stray frame
        outer.end()
        self.assertIsNone(manager.get()['request'])


class DummyRequest:
    def __init__(self):
        self.registry = object()


class GetCurrentRegistryTests(unittest.TestCase):
    def setUp(self):
        testing.setUp()

    def tearDown(self):
        testing.tearDown()

    def _callFUT(self):
        from pyramid.threadlocal import get_current_registry

        return get_current_registry()

    def test_it(self):
        from pyramid.threadlocal import manager

        try:
            manager.push({'registry': 123})
            self.assertEqual(self._callFUT(), 123)
        finally:
            manager.pop()


class GetCurrentRegistryWithoutTestingRegistry(unittest.TestCase):
    def _callFUT(self):
        from pyramid.threadlocal import get_current_registry

        return get_current_registry()

    def test_it(self):
        from pyramid.registry import global_registry

        self.assertEqual(self._callFUT(), global_registry)
