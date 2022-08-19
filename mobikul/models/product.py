# -*- coding: utf-8 -*-
##########################################################################
#
#    Copyright (c) 2015-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#
##########################################################################
from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def mobikul_publish_button(self):
        self.ensure_one()
        self.is_mobikul_available = not self.is_mobikul_available
        return True

    mobikul_categ_ids = fields.Many2many('mobikul.category', string='Mobikul Product Category')
    mobikul_status = fields.Selection([
        ('empty', 'Display Nothing'),
        ('in_stock', 'In-Stock'),
        ('out_stock', 'Out-of-Stock'),
    ], "Product Availability", default='empty', help="Adds an availability status on the mobikul product page.")
    is_mobikul_available = fields.Boolean("Published on App", default=1,
                                          help="Allow the end user to choose this price list")


class ProductPublicCategory(models.Model):
    _inherit = 'product.public.category'
    # this field is added for mobikul category merge
    mobikul_cat_id = fields.Many2one('mobikul.category', 'Mobikul Category')


class CrmTeam(models.Model):
    _inherit = "crm.team"

    mobikul_ids = fields.One2many('mobikul', 'salesteam_id', string='Mobikul',
                                  help="Mobikul is using these sales team.")
