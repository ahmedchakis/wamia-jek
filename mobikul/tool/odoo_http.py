# -*- coding: utf-8 -*-
#################################################################################
#
#    Copyright (c) 2015-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#
#################################################################################

from odoo import http
import logging
_logger = logging.getLogger(__name__)

# class RootInherit(http.Root):
#
#     def setup_db(self, httprequest):
#         res = super(RootInherit,self).setup_db(httprequest)
#         _logger.info("--------res----%r--",res)
#         if not res and httprequest.headers.get('mobikul-db'):
#             httprequest.session.db = httprequest.headers.get('mobikul-db')
#         else:
#             httprequest.session.db = http.db_monodb(httprequest)
#
# http.root = RootInherit()



def setup_db(self, httprequest):
    db = httprequest.session.db
    # Check if session.db is legit
    if db:
        if db not in http.db_filter([db], httprequest=httprequest):
            _logger.warn("Logged into database '%s', but dbfilter "
                         "rejects it; logging session out.", db)
            httprequest.session.logout()
            db = None

    if not db:
        if httprequest.headers.get('mobikul-db'):
            httprequest.session.db = httprequest.headers.get('mobikul-db')
        else:
            httprequest.session.db = http.db_monodb(httprequest)

http.Root.setup_db = setup_db
