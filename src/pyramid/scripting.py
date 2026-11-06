from collections import deque

from pyramid.config import global_registries
from pyramid.exceptions import ConfigurationError
from pyramid.interfaces import IRequestFactory, IRootFactory
from pyramid.request import Request, apply_request_extensions
from pyramid.threadlocal import RequestContext
from pyramid.traversal import DefaultRootFactory


def _settle_finished_callbacks(request, offset):
    # Settle only the finished callbacks registered for this scripting
    # generation (those appended after ``offset``).  A nested prepare,
    # even one reusing the same request, must not drain the outer
    # environment's callbacks when its closer runs.
    callbacks = getattr(request, 'finished_callbacks', None)
    if callbacks and len(callbacks) > offset:
        pending = deque()
        while len(callbacks) > offset:
            pending.appendleft(callbacks.pop())
        while pending:
            callback = pending.popleft()
            callback(request)
    if callbacks is not None and len(callbacks) == 0:
        # mirror Request._process_finished_callbacks when this generation
        # owned every remaining callback
        request.__dict__.pop('finished_callbacks', None)


def get_root(app, request=None):
    """Return a tuple composed of ``(root, closer)`` when provided a
    :term:`router` instance as the ``app`` argument.  The ``root``
    returned is the application root object.  The ``closer`` returned
    is a callable (accepting no arguments) that should be called when
    your scripting application is finished using the root.

    ``request`` is passed to the :app:`Pyramid` application root
    factory to compute the root. If ``request`` is None, a default
    will be constructed using the registry's :term:`Request Factory`
    via the :meth:`pyramid.interfaces.IRequestFactory.blank` method.

    Unlike :func:`prepare`, request extensions registered with
    :meth:`pyramid.config.Configurator.add_request_method` are **not**
    applied to the request, and its ``closer`` only ends the request
    context: finished callbacks are not invoked.  Use :func:`prepare`
    when the script needs a request pinned to the current request
    extension generation.
    """
    registry = app.registry
    if request is None:
        request = _make_request('/', registry)
    request.registry = registry
    ctx = RequestContext(request)
    ctx.begin()

    def closer():
        ctx.end()

    root = app.root_factory(request)
    return root, closer


def prepare(request=None, registry=None):
    """This function pushes data onto the Pyramid threadlocal stack
    (request and registry), making those objects 'current'.  It
    returns a dictionary useful for bootstrapping a Pyramid
    application in a scripting environment.

    ``request`` is passed to the :app:`Pyramid` application root
    factory to compute the root. If ``request`` is None, a default
    will be constructed using the registry's :term:`Request Factory`
    via the :meth:`pyramid.interfaces.IRequestFactory.blank` method.

    If ``registry`` is not supplied, the last registry loaded from
    :attr:`pyramid.config.global_registries` will be used. If you
    have loaded more than one :app:`Pyramid` application in the
    current process, you may not want to use the last registry
    loaded, thus you can search the ``global_registries`` and supply
    the appropriate one based on your own criteria.

    The function returns a dictionary composed of ``root``,
    ``closer``, ``registry``, ``request`` and ``root_factory``.  The
    ``root`` returned is the application's root resource object.  The
    ``closer`` returned is a callable (accepting no arguments) that
    should be called when your scripting application is finished
    using the root.  ``registry`` is the resolved registry object.
    ``request`` is the request object passed or the constructed request
    if no request is passed.  ``root_factory`` is the root factory used
    to construct the root.

    This function may be used as a context manager to call the ``closer``
    automatically:

    .. code-block:: python

       registry = config.registry
       with prepare(registry) as env:
           request = env['request']
           # ...

    .. versionchanged:: 1.8

       Added the ability to use the return value as a context manager.

    The request is pinned to the request extension generation that was
    current when ``prepare`` was called (see
    :func:`pyramid.request.apply_request_extensions`): a nested
    ``prepare`` settles only its own generation's finished callbacks and
    restores the outer environment (registry, request and extension view)
    when its ``closer`` runs.

    .. versionchanged:: 2.0

       Request finished callbacks added via
       :meth:`pyramid.request.Request.add_finished_callback` will be invoked
       by the ``closer``.

    """
    if registry is None:
        registry = getattr(request, 'registry', global_registries.last)
    if registry is None:
        raise ConfigurationError(
            'No valid Pyramid applications could be '
            'found, make sure one has been created '
            'before trying to activate it.'
        )
    if request is None:
        request = _make_request('/', registry)
    # NB: even though _make_request might have already set registry on
    # request, we reset it in case someone has passed in their own
    # request.
    request.registry = registry
    ctx = RequestContext(request)
    ctx.begin()
    # apply the current request extension generation and pin the request
    # to it before the root factory runs; get_root deliberately skips this
    apply_request_extensions(request)

    # remember how many finished callbacks predate this scripting
    # generation so the closer only settles its own callbacks and never
    # drains an outer generation when prepares are nested
    existing_callbacks = getattr(request, 'finished_callbacks', None)
    finished_offset = (
        len(existing_callbacks) if existing_callbacks is not None else 0
    )

    def closer():
        _settle_finished_callbacks(request, finished_offset)
        ctx.end()

    root_factory = registry.queryUtility(
        IRootFactory, default=DefaultRootFactory
    )
    root = root_factory(request)
    if getattr(request, 'context', None) is None:
        request.context = root
    return AppEnvironment(
        root=root,
        closer=closer,
        registry=registry,
        request=request,
        root_factory=root_factory,
    )


class AppEnvironment(dict):
    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self['closer']()


def _make_request(path, registry=None):
    """Return a :meth:`pyramid.request.Request` object anchored at a
    given path. The object returned will be generated from the supplied
    registry's :term:`Request Factory` using the
    :meth:`pyramid.interfaces.IRequestFactory.blank` method.

    This request object can be passed to :meth:`pyramid.scripting.get_root`
    or :meth:`pyramid.scripting.prepare` to initialize an application in
    preparation for executing a script with a proper environment setup.
    URLs can then be generated with the object, as well as rendering
    templates.

    If ``registry`` is not supplied, the last registry loaded from
    :attr:`pyramid.config.global_registries` will be used. If you have
    loaded more than one :app:`Pyramid` application in the current
    process, you may not want to use the last registry loaded, thus
    you can search the ``global_registries`` and supply the appropriate
    one based on your own criteria.
    """
    if registry is None:
        registry = global_registries.last
    request_factory = registry.queryUtility(IRequestFactory, default=Request)
    request = request_factory.blank(path)
    request.registry = registry
    return request
