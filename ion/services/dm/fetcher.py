#!/usr/bin/env python

"""
@file ion/services/dm/fetcher.py
@package ion.services.dm.fetcher Remimpliment fetcher as an LCA service
@author Paul Hubbard
@date 5/7/10
@brief Porting the fetcher from DX to LCAarch.
"""

import logging

from twisted.internet import defer
import httplib as http
import urlparse
import logging

from ion.core.base_process import ProtocolFactory
from ion.services.base_service import BaseService, BaseServiceClient

class FetcherService(BaseService):
    """
    Fetcher, implemented as a service.

    Service declaration - seems similar to the Zope methods
    @todo Dependencies - perhaps pub-sub?
    @note These are not class methods!
    """
    logging.info('Declaring fetcher...')
    declare = BaseService.service_declare(name='fetcher',
                                          version='0.1.1',
                                          dependencies=[])
    """
    @todo Declare fetcher name into dns-equivalent...
    """
    def _reassemble_headers(self, result):
        """
        @brief Convert an array of tuples into http headers
        @todo check for library routine to do this.
        """
        hstr = ''
        for x in result.getheaders():
            hstr = hstr + '%s: %s\r\n' % (x[0], x[1])

        return hstr

    @defer.inlineCallbacks
    def _http_op(self, operation, src_url, msg):
        """
        @brief Inner method for GET and HEAD, does fetch and reply
        @param operation 'GET' or 'HEAD'
        @param src_url Source URL
        @retval send_ok or send_err as required
        """
        assert(operation in ['GET', 'HEAD'])

        src = urlparse.urlsplit(src_url)
        try:
            conn = http.HTTPConnection(src.netloc)
            # @bug Need to merge path with query, no canned fn in urlparse lib
            conn.request(operation, src.path)
            res = conn.getresponse()
        except gaierror, ge:
            logging.exception()
            yield self.reply_err(msg, content=str(ge))

        # Did it succeed?
        if res.status == 200:
            hstr = self._reassemble_headers(res)
            # @note read on HEAD returns no data
            hstr = hstr + '\n' + res.read()

            yield self.reply_ok(msg, content=hstr)

        yield self.reply_err(msg, content='%s: %s' % (res.status, res.reason))

    @defer.inlineCallbacks
    def op_get_head(self, content, headers, msg):
        """
        A lot of DAP clients break the spec and use the HEAD http verb.
        Sigh.

        Much easier to implement in httplib than twisted.
        """
        yield self._http_op('HEAD', content, msg)

    @defer.inlineCallbacks
    def op_get_url(self, content, headers, msg):
        """
        Refactored page puller using httplib instead of client.getPage
        """
        yield self._http_op('GET', content, msg)

    @defer.inlineCallbacks
    def op_get_dap_dataset(self, content, headers, msg):
        """
        The core of the fetcher: function to grab an entire DAP dataset and
        send it off into the cloud.
        """
        logging.warn('Implement me!')
        yield self.reply_err(msg, 'reply', {'value':'no code!'}, {})

class FetcherClient(BaseServiceClient):
    """
    Client class for the fetcher.
    @note RPC style interactions
    """
    def __init__(self, proc=None, **kwargs):
        if not 'targetname' in kwargs:
            kwargs['targetname'] = "fetcher"
        BaseServiceClient.__init__(self, proc, **kwargs)

    @defer.inlineCallbacks
    def get_head(self, requested_url):
        """
        HTTP HEAD verb for a given URL. Not in the DAP spec, but used regardless.
        """
        yield self._check_init()

        logging.info('Sending HEAD request to fetcher...')
        (content, headers, msg) = yield self.rpc_send('get_head', requested_url)
        if 'ERROR' in content:
            raise ValueError('Error on URL: ' + content['failure'])
        defer.returnValue(content)


    @defer.inlineCallbacks
    def get_url(self, requested_url):
        """
        @todo look up fetcher in dns
        send to same
        return unpacked reply
        """
        yield self._check_init()

        logging.info('Sending request')
        (content, headers, msg) = yield self.rpc_send('get_url', requested_url)
        if 'ERROR' in content:
            raise ValueError('Error on URL: ' + content['failure'])
        defer.returnValue(content)

    def _rewrite_headers(self, old_headers):
        """
        Rewrite the message headers so that the reply-to points to the original
        sender and uses the same conversation id. Easy way to implement third-
        party messaging/coordination.
        """
        new_headers = {}
        try:
            new_headers['reply-to'] = old_headers['reply-to']
            new_headers['conv-id'] = old_headers['conv-id']
        except KeyError, ke:
            logging.exception('missing header!')
            raise ke

        return new_headers

    @defer.inlineCallbacks
    def forward_get_url(self, content, headers):
        """
        Forward a message to the fetcher.
        Reach in and rewrite the reply-to and conversation id headers, so
        that the fetcher can reply directly to the proxy and bypass the
        coordinator.
        """
        logging.debug('Fetcher forwarding URL')
        yield self.send('get_url', content, self._rewrite_headers(headers))

    @defer.inlineCallbacks
    def forward_get_dap_dataset(self, content, headers):
        """
        Same as forward_get_url, different verb.
        """
        yield self.send('get_dap_dataset', content, self._rewrite_headers(headers))

# If loaded as a module, spawn the process
factory = ProtocolFactory(FetcherService)