# -*- coding: utf-8 -*-
##########################################################################
#
#    Copyright (c) 2015-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#
##########################################################################
import logging
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    last_mobikul_so_id = fields.Many2one('sale.order', string='Last Order from Mobikul App')
    banner_image = fields.Binary('Banner Image', attachment=True)
    token_ids = fields.One2many('fcm.registered.devices', 'customer_id',
                                string='Registered Devices', readonly=True)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    cart_count = fields.Integer(compute='_compute_cart_count', string='Cart Count')

    @api.depends('order_line.product_uom_qty', 'order_line.product_id')
    def _compute_cart_count(self):
        is_wesiteSaleDelivery = self.env['mobikul'].sudo(
        ).check_mobikul_addons().get('website_sale_delivery')
        for order in self:
            if is_wesiteSaleDelivery:
                order.cart_count = int(
                    sum([line.product_uom_qty for line in order.order_line if not line.is_delivery]))
            else:
                order.cart_count = int(sum(order.mapped('order_line.product_uom_qty')))


class PaymentAcquirer(models.Model):
    _inherit = 'payment.acquirer'

    is_mobikul_available = fields.Boolean(
        'Visible in Mobikul', copy=False,
        help="Make this payment acquirer available on App")
    mobikul_reference_code = fields.Char(
        'Mobikul Reference Code', copy=False,
        help="Unique Code in order to integrate it with Mobikul App.")
    mobikul_pre_msg = fields.Text('Message to Display', copy=False,
                                  translate=True, help="this field is depricated from mobikul")
    mobikul_extra_key = fields.Char('Extra Keys', copy=False)
