# -*- coding: utf-8 -*-
##########################################################################
#
#    Copyright (c) 2015-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#
##########################################################################
from ast import literal_eval
from odoo import api, fields, models, _, SUPERUSER_ID
from odoo.tools.translate import html_translate
# import datetime
from odoo.exceptions import UserError
import random
import string
import inspect
import json
import re
from .fcmAPI import FCMAPI
from datetime import datetime, timedelta
import logging
_logger = logging.getLogger(__name__)
# from odoo.addons.base.ir.ir_mail_server import MailDeliveryException


def _displayWithCurrency(lang_obj, amount, symbol, position):
    fmt = "%.{0}f".format(2)  # currency.decimal_places
    # lang = cls.env['res.lang']._lang_get(cls.env.context.get('lang') or 'en_US')

    formatted_amount = lang_obj.format(
        fmt, amount, grouping=True, monetary=True)  # currency.round(amount)
    # _logger.info("-------%s"%formatted_amount)
    return "%s%s" % (symbol, formatted_amount) if position == "before" else "%s%s" % (formatted_amount, symbol)


@api.model
def _lang_get(cls):
    return cls.env['res.lang'].get_installed()


def _default_unique_key(size, chars=string.ascii_uppercase + string.digits):
    return ''.join(random.choice(chars) for x in range(size))


def _get_image_url(base_url, model_name, record_id, field_name, write_date=0, width=0, height=0):
    """ Returns a local url that points to the image field of a given browse record. """
    if base_url and not base_url.endswith("/"):
        base_url = base_url+"/"
    if width or height:
        return '%sweb/image/%s/%s/%s/%sx%s?unique=%s' % (base_url, model_name, record_id, field_name, width, height, re.sub('[^\d]', '', fields.Datetime.to_string(write_date)))
    else:
        return '%sweb/image/%s/%s/%s?unique=%s' % (base_url, model_name, record_id, field_name, re.sub('[^\d]', '', fields.Datetime.to_string(write_date)))


def _getProductData(p_data, base_url, currency_symbol, currency_position, lang_obj,discount_policy):
    result = []
    without_discount_policy = discount_policy == 'without_discount'
    for prod in p_data:
        result.append({
            'templateId': prod['id'] or '',
            'name': prod['name'] or '',

            # 'priceUnit': _displayWithCurrency(lang_obj, prod['lst_price'] or 0, currency_symbol, currency_position),
            # 'priceReduce': prod['price'] < prod['lst_price'] and _displayWithCurrency(lang_obj, prod['price'] or 0, currency_symbol, currency_position) or "",
            'priceUnit': _displayWithCurrency(lang_obj, without_discount_policy and prod['lst_price'] or prod['price'] or 0, currency_symbol, currency_position),
            'priceReduce':without_discount_policy and _displayWithCurrency(lang_obj, prod['price'] or 0, currency_symbol, currency_position) or "",

            'productId': prod['product_variant_id'] and prod['product_variant_id'][0] or '',
            'productCount': prod['product_variant_count'] or 0,
            'description': prod['description_sale'] or '',
            'thumbNail': _get_image_url(base_url, 'product.template', prod['id'], 'image', prod['write_date'])
        })
    return result


def _get_product_fields():
    return ['name', 'product_variant_id', 'product_variant_count', 'price', 'description_sale', 'lst_price', 'website_price', 'write_date']


def _get_product_domain():
    return [("sale_ok", "=", True), ("is_mobikul_available", "=", True)]

# def authenticate_request(fn):
#   def ret_fn(*args, **kwargs):
#       # userdata = inspect.getargspec(fn)
#       # result = args[0].authenticate(args[1].get('usr'),args[1].get('pwd'))
#       return "result %r %r"%(str(args), str(kwargs))
#       if not result['success']:
#           return "result %r %r "%(args, kwargs)
#       else:
#           return fn(*args,**kwargs)
#   return ret_fn


class Mobikul(models.Model):
    _name = "mobikul"
    _description = "Mobikul Model"

    @api.model
    def _create_so(self, partner, local):
        local = local or {}
        result = {"success": True}
        addr = partner.address_get(['delivery'])
        so_data = {
            'partner_id': partner.id,
            'pricelist_id': self._context.get('pricelist'),
            'payment_term_id': partner.property_payment_term_id.id,
            'team_id': local.get("teamId"),
            'partner_invoice_id': partner.id,
            'partner_shipping_id': addr['delivery'],
            'user_id': local.get("salespersonId"),
        }
        company = self.env['product.pricelist'].browse(
            self._context.get('pricelist')).sudo().company_id
        if company:
            so_data['company_id'] = company.id
        result['order'] = self.env['sale.order'].sudo().create(so_data)

        partner.write({'last_mobikul_so_id': result['order'].id})
        result['cartId'] = result['order'].id

        return result

    @api.model
    def _create_so_line(self, order, Product, qty=1):
        result = {"success": True}
        SaleOrderLineSudo = self.env['sale.order.line'].sudo()

        product_context = dict(self.env.context)
        product_context.setdefault('lang', order.partner_id.lang)
        product_context.update({
            'partner': order.partner_id.id,
            'quantity': qty,
            'date': order.date_order,
            'pricelist': order.pricelist_id.id,
        })
        product = Product.with_context(product_context)

        so_line_data = {
            'name': product.name,
            'product_id': product.id,
            'product_uom_qty': qty,
            'order_id': order.id,
            'product_uom': product.uom_id.id,
            'price_unit': product.price,
        }
        order_line = SaleOrderLineSudo.create(so_line_data)
        order_line.product_id_change()
        order_line.product_uom_change()
        order_line._onchange_discount()
        return result

    # def _get_line_description(self, order, product_id, attributes=None):
    #   if not attributes:
    #       attributes = {}

    #   product = self.env['product.product'].with_context(product_context).browse(product_id)

    #   name = product.display_name

    #   # add untracked attributes in the name
    #   untracked_attributes = []
    #   for k, v in attributes.items():
    #       # attribute should be like 'attribute-48-1' where 48 is the product_id, 1 is the attribute_id and v is the attribute value
    #       attribute_value = self.env['product.attribute.value'].sudo().browse(int(v))
    #       if attribute_value and not attribute_value.attribute_id.create_variant:
    #           untracked_attributes.append(attribute_value.name)
    #   if untracked_attributes:
    #       name += '\n%s' % (', '.join(untracked_attributes))

    #   if product.description_sale:
    #       name += '\n%s' % (product.description_sale)

    #   return name

    @api.model
    def _validate(self, api_key, context=None):
        context = context or {}
        response = {'success': False, 'responseCode': 0, 'message': _('Unknown Error !!!')}
        if not api_key:
            response['message'] = _('Invalid/Missing Api Key !!!')
            return response
        try:
            # Get Mobikul Conf
            mobikul = self.env['mobikul'].sudo().search([], limit=1)
            if not mobikul:
                response['responseCode'] = 1
                response['message'] = _("Mobikul Configuration not found !!!")
            elif mobikul.api_key != api_key:
                response['responseCode'] = 1
                response['message'] = _("API Key is invalid !!!")
            else:
                response['success'] = True
                response['responseCode'] = 2
                response['message'] = _('Login successfully.')
                response['lang'] = context.get(
                    'lang') or mobikul.default_lang and mobikul.default_lang.code or "en_US"
                response['itemsPerPage'] = mobikul.product_limit
                response['pricelist'] = mobikul.pricelist_id and mobikul.pricelist_id.id or 1
                response['local'] = {
                    'pricelistObj' : mobikul.pricelist_id,
                    'currencySymbol': mobikul.pricelist_id and mobikul.pricelist_id.currency_id and mobikul.pricelist_id.currency_id.symbol or "",
                    'currencyPosition': mobikul.pricelist_id and mobikul.pricelist_id.currency_id and mobikul.pricelist_id.currency_id.position or "",
                    'teamId': mobikul.salesteam_id and mobikul.salesteam_id.id or False,
                    'salespersonId': mobikul.salesperson_id and mobikul.salesperson_id.id or False,
                    'lang_obj': self.env['res.lang']._lang_get(response['lang']),
                    'websiteObj': mobikul.website_id,
                    'currency_id':mobikul.pricelist_id.currency_id,
                    'discount_policy':mobikul.pricelist_id and mobikul.pricelist_id.discount_policy or 'with_discount',
                }
                response['addons'] = self.check_mobikul_addons()
        except Exception as e:
            response['responseCode'] = 3
            response['message'] = _("Login Failed:")+"%r" % e.message or e.name
        return response

    @api.model
    def _get_image_url(self, model_name, record_id, field_name, write_date=0, width=0, height=0, context=None):
        """ Returns a local url that points to the image field of a given browse record. """
        context = context or {}
        if context.get('base_url', "") and not context['base_url'].endswith("/"):
            context['base_url'] = context['base_url'] + "/"
        if width or height:
            return '%sweb/image/%s/%s/%s/%sx%s?unique=%s' % (context.get('base_url'), model_name, record_id, field_name, width, height, re.sub('[^\d]', '', fields.Datetime.to_string(write_date)))
        else:
            return '%sweb/image/%s/%s/%s?unique=%s' % (context.get('base_url'), model_name, record_id, field_name, re.sub('[^\d]', '', fields.Datetime.to_string(write_date)))

    @api.model
    def _get_cat_info(self, categ_obj, context=None):
        context = context or {}
        cat_data = {
            "category_id": categ_obj.id,
            "name": categ_obj.name or "",
            "children": [],
            "banner": self._get_image_url('mobikul.category', categ_obj.id, 'banner', categ_obj.write_date, context=context),
            "icon": self._get_image_url('mobikul.category', categ_obj.id, 'icon', categ_obj.write_date, context=context),
        }
        return cat_data

    @api.model
    def _recursive_cats(self, categ_obj, context=None):
        context = context or {}
        data = self._get_cat_info(categ_obj, context)
        if categ_obj.child_id:
            for cat_child in categ_obj.child_id:
                data['children'].append(self._recursive_cats(cat_child, context))
        return data

    @api.model
    def fetch_categories(self, context=None):
        context = context or {}
        all_cats = []
        if context.get('website_category', False):
            return all_cats
        else:
            cat_obj = self.env['mobikul.category'].sudo()
        top_cats = cat_obj.search([('parent_id', '=', False)])
        for top_cat in top_cats:
            all_cats.append(self._recursive_cats(top_cat, context))
        return all_cats

    @api.model
    def fetch_featured_categories(self, context=None):
        context = context or {}
        all_fcats = []
        if context.get('website_category', False):
            return all_fcats
        else:
            cat_obj = self.env['mobikul.category'].sudo()
        f_cats = cat_obj.search([('type', '=', 'featured')])

        for f_cat in f_cats:
            temp_f = {
                'categoryName': f_cat.name or "",
                'categoryId': f_cat.id
            }
            temp_f['url'] = self._get_image_url(
                'mobikul.category', f_cat.id, 'icon', f_cat.write_date, context=context)
            all_fcats.append(temp_f)
        return all_fcats

    @api.model
    def fetch_product_sliders(self, context=None):
        context = context or {}
        allProductSliders = []
        pSlider_obj = self.env['mobikul.product.slider'].sudo()
        p_sliders = pSlider_obj.search([])
        for p_slider in p_sliders:
            products = p_slider.get_product_data(context)['products']
            if not len(products):
                continue
            temp_s = {
                'title': p_slider.name or "",
                'item_display_limit': p_slider.item_display_limit,
                'slider_mode': p_slider.slider_mode or "",
                'product_img_position': p_slider.product_img_position or "",
                'products': products,
                'url': "/mobikul/sliderProducts/%d" % p_slider.id,
                # 'color':p_slider.bk_color or ""
            }
            if p_slider.display_banner:
                temp_s['backImage'] = self._get_image_url(
                    'mobikul.product.slider', p_slider.id, 'banner', p_slider.write_date, context=context)
            allProductSliders.append(temp_s)
        return allProductSliders

    @api.model
    def fetch_user_info(self, user_obj, context=None):
        context = context or {}
        temp_i = {
            'customerBannerImage': self._get_image_url('res.partner', user_obj.partner_id.id, 'banner_image', user_obj.partner_id.write_date, context=context),
            'customerProfileImage': self._get_image_url('res.partner', user_obj.partner_id.id, 'image', user_obj.partner_id.write_date, context=context),
            'cartId': user_obj.partner_id.last_mobikul_so_id and user_obj.partner_id.last_mobikul_so_id.id or '',
            # 'cartCount': user_obj.partner_id.last_website_so_id and user_obj.partner_id.last_website_so_id.cart_count or 0,
            'themeCode': '?',
            'customerName': user_obj.partner_id.name or "",
            'customerEmail': user_obj.login or "",
            'customerLang': user_obj.partner_id.lang.split('_')[0],
        }
        # if context.has_key('website') and context['website']:
        #   temp_i['cartId'] = user_obj.partner_id.last_website_so_id and user_obj.partner_id.last_website_so_id.id or ''
        #   temp_i['cartCount'] = user_obj.partner_id.last_website_so_id and user_obj.partner_id.last_website_so_id.cart_count or 0
        # else:
        #   temp_i['cartId'] = user_obj.partner_id.last_mobikul_so_id and user_obj.partner_id.last_mobikul_so_id.id or ''
        #   temp_i['cartCount'] = user_obj.partner_id.last_mobikul_so_id and user_obj.partner_id.last_mobikul_so_id.cart_count or 0
        return temp_i

    @api.model
    def authenticate(self, credentials, detailed=False, isSocialLogin=False, context=None):
        context = context or {}
        response = {'success': False, 'responseCode': 0, 'message': _('Unknown Error !!!')}
        user = False
        if not isinstance(credentials, dict):
            response['message'] = _('Data is not in Dictionary format !!!')
            return response
        if isSocialLogin:
            if not all(k in credentials for k in ('authProvider', 'authUserId')):
                response['message'] = _('Insufficient data to authenticate !!!')
                return response
            provider = self._getAuthProvider(credentials['authProvider'])
            try:
                user = self.env['res.users'].sudo().search(
                    [('oauth_uid', '=', credentials['authUserId']), ('oauth_provider_id', '=', provider)])
                if not user:
                    response['responseCode'] = 1
                    response['message'] = _("Social-Login: No such record found.")
            except Exception as e:
                response['responseCode'] = 3
                response['message'] = _("Social-Login Failed.")
                response['details'] = "%r" % e
        else:
            if not all(k in credentials for k in ('login', 'pwd')):
                response['message'] = _('Insufficient data to authenticate !!!')
                return response
            try:
                user = self.env['res.users'].sudo().search([('login', '=', credentials['login'])])
                if user:
                    user.sudo(user.id)._check_credentials(credentials['pwd'])
                else:
                    response['responseCode'] = 1
                    response['message'] = _("Invalid email address.")
                    response['accessDenied'] = True
            except Exception as e:
                user = False
                response['responseCode'] = 3
                response['message'] = _("Login Failed.")
                response['details'] = "%r" % e
                response['accessDenied'] = True
        if user:
            Partner = user.partner_id
            if Partner:
                last_order = Partner.last_mobikul_so_id
                if last_order.state in ['sale','done','cancel']:
                    Partner.last_mobikul_so_id = False
            try:
                response['success'] = True
                response['responseCode'] = 2
                response['customerId'] = user.partner_id.id
                response['userId'] = user.id
                response['cartCount'] = user.partner_id.last_mobikul_so_id and user.partner_id.last_mobikul_so_id.cart_count or 0
                response['message'] = _('Login successfully.')
                if self.check_mobikul_addons().get('wishlist'):
                    response['WishlistCount'] = len(user.partner_id.wishlist_ids)
                if self.check_mobikul_addons().get('email_verification'):
                    response['is_email_verified'] = user.wk_token_verified
                if self.check_mobikul_addons().get('odoo_marketplace'):
                    response['is_seller'] = user.partner_id.seller and user.partner_id.state == 'approved'
                    if user.partner_id.seller:
                        response['seller_group'] = self.check_seller_state(user)
                        response['seller_state'] = user.partner_id.state
                if detailed:
                    response.update(self.fetch_user_info(user, context=context))
            except Exception as e:
                response['responseCode'] = 3
                response['message'] = _("Login Failed.")
                response['details'] = "%r" % e
        return response

    def check_seller_state(self, user):
        user_groupObj = self.env['ir.model.data'].sudo()
        user_group_ids = user.groups_id.ids
        xml_ids = ["marketplace_seller_group",
                   "marketplace_officer_group", "marketplace_manager_group"]
        for xml_id in xml_ids:
            mp_group = user_groupObj.get_object_reference('odoo_marketplace', xml_id)[
                1] in user_group_ids and xml_id or ""
            break
        return mp_group

    def check_mobikul_addons(self):
        result = {}
        ir_model_obj = self.env['ir.module.module'].sudo()
        result['wishlist'] = ir_model_obj.search(
            [('state', '=', 'installed'), ('name', '=', 'website_sale_wishlist')]) and True or False
        result['review'] = ir_model_obj.search(
            [('state', '=', 'installed'), ('name', '=', 'wk_review')]) and True or False
        result['email_verification'] = ir_model_obj.search(
            [('state', '=', 'installed'), ('name', '=', 'email_verification')]) and True or False
        result['odoo_marketplace'] = ir_model_obj.search(
            [('state', '=', 'installed'), ('name', '=', 'odoo_marketplace')]) and True or False
        result['website_sale_delivery'] = ir_model_obj.search(
            [('state', '=', 'installed'), ('name', '=', 'website_sale_delivery')]) and True or False
        result['odoo_gdpr'] = ir_model_obj.search(
            [('state', '=', 'installed'), ('name', '=', 'odoo_gdpr')]) and True or False
        result['authorize_net_mobikul_integration'] = ir_model_obj.search(
            [('state', '=', 'installed'), ('name', '=', 'authorize_net_mobikul_integration')]) and True or False
        return result

    def email_verification_defaults(self):
        return self.env['email.verification.config'].sudo().get_values()

    def review_defaults(self):
        return self.env['website.review.config'].sudo().get_values()

    @api.model
    def homePage(self, cust_data, context):
        context = context or {}
        response = {}

        # Get base url
        # if not context.has_key("base_url"):
        if not 'base_url' in context:

            context['base_url'] = self.env['ir.config_parameter'].get_param('web.base.url')

        # Get Mobikul Conf
        mobikul = self.env['mobikul'].sudo().search([], limit=1)

        # Get all Categories
        response['categories'] = self.fetch_categories(context=context)

        # Get all Banners
        response['bannerImages'] = self.fetch_banners(context=context)

        # Get all Featured categories
        response['featuredCategories'] = self.fetch_featured_categories(context=context)

        # Get all Product Sliders
        response['productSliders'] = self.fetch_product_sliders(context=context)

        return response

    @api.model
    def fetch_countries(self):
        MobObj = self.sudo().search([], limit=1)
        domain = []
        if MobObj.country_ids:
            domain = [("id", "in", [c.id for c in MobObj.country_ids])]
        countries = self.env['res.country'].sudo().search_read(domain, fields=['name', 'state_ids'])
        return countries

    @api.model
    def fetch_banners(self, context=None):
        context = context or {}
        all_banners = []
        MobBanners = self.env['mobikul.banners'].sudo().search_read([])
        for banner in MobBanners:
            temp_d = {
                "bannerName": banner['name'],
                "bannerType": banner['banner_action'],
                "id": '',
            }
            if banner['banner_action'] == "product":
                temp_d['id'] = banner["product_id"][0]
            elif banner['banner_action'] == "category":
                temp_d['id'] = banner["category_id"][0]
            elif banner['banner_action'] == "custom":
                temp_d['domain'] = "[('id','in',%r)]" % banner["product_ids"]
            if banner['image']:
                temp_d['url'] = self._get_image_url(
                    'mobikul.banners', banner['id'], 'image', banner['write_date'], context=context)
            else:
                temp_d['url'] = banner['url']
            all_banners.append(temp_d)
        # else:
        #   response['message'] = "No active banners found !!!"
        #   response['error_message'] = "Create some Banners, re-verify their publishing date."
        return all_banners

    @api.model
    def resetPassword(self, login):
        response = {'success': False}
        # MobikulConfigParam = self.search_read([], limit=1)[0]
        # if MobikulConfigParam['reset_password_enabled']:
        try:
            if login:
                self.env['res.users'].sudo().reset_password(login)
                response['success'] = True
                response['message'] = _(
                    "An email has been sent with credentials to reset your password")
            else:
                response['message'] = _("No login provided.")
        except Exception as e:
            # response['message'] = _("There is some error occurred. Please try again after some time.")
            response['message'] = _("Invalid Username/Email.")
        # else:
        #   response['message'] = "Error: Permission not granted !!!"
        return response

    @api.model
    def _getAuthProvider(self, provider):
        if provider == "GMAIL":
            google_provider = self.env.ref('auth_oauth.provider_google')
            return google_provider and google_provider.id or False
        elif provider == "FACEBOOK":
            facebook_provider = self.env.ref('auth_oauth.provider_facebook')
            return facebook_provider and facebook_provider.id or False
        elif provider == "TWITTER":
            twitter_provider = self.env.ref('auth_oauth.provider_twitter')
            return twitter_provider and twitter_provider.id or False
        return False

    @api.model
    def _doSignup(self, data):
        template_user_id = literal_eval(self.env['ir.config_parameter'].get_param(
            'auth_signup.template_user_id', 'False'))
        template_user = self.env['res.users'].browse(template_user_id)
        if not template_user.exists():
            return [False, 'Invalid template user']

        values = {key: data.get(key) for key in ('login', 'name')}
        values['email'] = data.get('email') or values.get('login')
        # values['lang'] = self.lang
        values['active'] = True
        no_invitation_mail = True
        if data.get('isSocialLogin', False):
            values['oauth_uid'] = data.get('authUserId', "")
            values['oauth_access_token'] = data.get('authToken', "")
            values['oauth_provider_id'] = self._getAuthProvider(data.get('authProvider', ""))
            values['email'] = values.get('email', 'provider_%s_user_%s' %
                                         (values['oauth_provider_id'], values['oauth_uid']))
            values['password'] = data.get("password", values['oauth_uid'])
            if self.check_mobikul_addons().get('email_verification'):
                values['wk_token_verified'] = True
            if not values['oauth_uid'] or not values['oauth_provider_id'] or not values['name'] or not values['email']:
                return [False, "Insufficient data to authenticate."]
        else:
            values['password'] = data.get('password', "")
            no_invitation_mail = values['password'] and True or False
            if not values['name'] or not values['email']:
                return [False, "Insufficient data to authenticate."]
            # if not all(values.itervalues()): return [False,"The form was not properly filled in."]
            # if values.get('password') != data.get('confirm_password'): return [False, "Passwords do not match; please retype them."]
        try:
            with self.env.cr.savepoint():
                if self.check_mobikul_addons().get('odoo_marketplace') and data.get('is_seller'):
                    seller_msg = self.isMarketplaceSignup(template_user, values, data)
                    if seller_msg.get('status'):
                        return [True, seller_msg.get('user').id, seller_msg.get('user').partner_id.id, seller_msg.get('msg')]
                    else:
                        return [False, _("Seller profile 'url_handler' is not unique or absent.")]
                else:
                    user = template_user.with_context(
                        no_reset_password=no_invitation_mail).copy(values)
                    return [True, user.id, user.partner_id.id, " "]
        except UserError as e:
            return [False,e.name]
        except Exception as e:
            # copy may failed if asked login is not available.
            # return [False,"Error: %r"%e]
            return [False, _("There is some problem in creating account. Please try again later.")]
        return [False, "Unknown Error"]

    def isMarketplaceSignup(self, template_user, values, data):
        if data.get('url_handler') and self.checkSellerUniqueUrl(data.get('url_handler')):
            user = template_user.with_context(no_reset_password=True).copy(values)
            if user:
                self.set_marketplace_group_user(user)
                # user.partner_id.country = "India"
                user.partner_id.seller = True
                user.partner_id.url_handler = data.get('url_handler')
                user.partner_id.country_id = data.get('country_id')
                return {'status': True, 'msg': _("Seller created successfully"), 'user': user}
            else:
                {"status": False, "msg": _("Something went wrong please try again.")}
        else:
            return {"status": False, "msg": _("Seller profile 'url_handler' is not unique or absent.")}

    def set_marketplace_group_user(self, userObj):
        user_group_id = self.env['ir.model.data'].get_object_reference(
            'odoo_marketplace', 'marketplace_draft_seller_group')[1]
        groups_obj = self.env["res.groups"].browse(user_group_id)
        if groups_obj:
            for group_obj in groups_obj:
                group_obj.write({"users": [(4, userObj.id, 0)]})
                return True
        else:
            return False

    def checkSellerUniqueUrl(self, url):
        if url:
            if not re.match('^[a-zA-Z0-9-_]+$', url) or re.match('^[-_][a-zA-Z0-9-_]*$', url) or re.match('^[a-zA-Z0-9-_]*[-_]$', url):
                raise UserError(_("Only alphanumeric([0-9],[a-z]) and some special characters(-,_) are allowed, Spaces are not allowed."))
            check_url_existObj = self.env['res.partner'].sudo().search(
                [('url_handler', '=', url)], limit=1)
            if len(check_url_existObj) == 0:
                return True
            else:
                return False
        else:
            return False

    @api.model
    def signUp(self, form_data):
        response = {'success': False}
        # MobikulConfigParam = self.search_read([], limit=1)[0]
        # if MobikulConfigParam['signup_enabled']:

        try:
            if form_data.get('isSocialLogin', False):
                provider = self._getAuthProvider(form_data['authProvider'])
                user = self.env['res.users'].sudo().search(
                    [('oauth_uid', '=', form_data['authUserId']), ('oauth_provider_id', '=', provider)])
                if user:
                    response['success'] = True
                    response['message'] = _("Login Successfully.")
                    response['userId'] = user.id
                    response['customerId'] = user.partner_id.id
                    return response
            if 'login' in form_data:
                if self.env['res.users'].sudo().search([("login", "=", form_data['login'])]):
                    # response['message'] = _("Another user is already registered using this email address.")
                    response['message'] = _("This mail is already registered with us. ")

                else:
                    result = self._doSignup(form_data)
                    if result[0]:
                        response['success'] = True
                        # response['message']   = "An invitation has been sent to mentioned email, please accept it and set your password to complete the registration process."
                        # response['message']   = "A validation e-mail has been sent to your e-mail address."
                        response['message'] = _("Created Successfully.")
                        response['userId'] = result[1]
                        response['customerId'] = result[2]
                        response['seller_message'] = result[3]
                    else:
                        response['message'] = _("Could not create a new account: ")+"%s" % result[1]
            else:
                response['message'] = _("No login provided.")
        except Exception as e:
            response['message'] = _("Could not create a new account.:")+" %r" % e.message or e.name
        # else:
        #   response['message'] = "Error: Permission not granted !!!"
        return response

    @api.model
    def getDefaultData(self):
        IrConfigParam = self.env['ir.config_parameter']
        temp = {}
        temp['allow_resetPwd'] = literal_eval(
            IrConfigParam.get_param('auth_signup.reset_password', 'False'))
        temp['allow_signup'] = literal_eval(
            IrConfigParam.get_param('auth_signup.allow_uninvited', 'False'))
        temp['allow_guestCheckout'] = literal_eval(
            IrConfigParam.get_param('mobikul.allow_guest', 'False'))
        temp['allow_gmailSign'] = literal_eval(
            IrConfigParam.get_param('mobikul.gmail_signin', 'False'))
        temp['allow_facebookSign'] = literal_eval(
            IrConfigParam.get_param('mobikul.facebook_signin', 'False'))
        temp['allow_twitterSign'] = literal_eval(
            IrConfigParam.get_param('mobikul.twitter_signin', 'False'))
        data = self.check_mobikul_addons()
        #temp['dule_website_wishlist'] = data.get("wishlist")
        temp['allowShipping'] = data.get("website_sale_delivery")
        return temp

    def _default_order_mail_template(self):
        return self.env.ref('sale.email_template_edi_sale').id

    def fetch_products(self, **kwargs):
        """
        Extra Parameters: domain, limit, fields, offset, order
        """
        domain = _get_product_domain()
        result = {'offset': kwargs.get('offset', 0)}
        try:
            if 'domain' in kwargs:
                domain += literal_eval(kwargs['domain'])
        except:
            pass
        if 'barcode' in kwargs:
            domain += [('barcode', '=', kwargs['barcode'])]
        if 'search' in kwargs:
            for s in kwargs['search'].split(" "):
                domain += [('name', 'ilike', s)]
        if 'cid' in kwargs:
            domain += [('mobikul_categ_ids', 'child_of', int(kwargs['cid']))]

        ProductObj = self.env['product.template'].sudo()
        result['tcount'] = ProductObj.search_count(domain)
        product_data = ProductObj.search_read(domain, limit=kwargs.get(
            'limit', 5), offset=result["offset"], order=kwargs.get('order', 0), fields=_get_product_fields())

        result['products'] = _getProductData(product_data, kwargs.get('base_url', self._get_base_url(
        )), kwargs.get('currencySymbol'), kwargs.get('currencyPosition'), kwargs.get('lang_obj'), kwargs.get('discount_policy'))
        return result

    def _get_base_url(self):
        return self.env['ir.config_parameter'].get_param('web.base.url')

    def _default_language(self):
        lc = self.env['ir.default'].get('res.partner', 'lang')
        dl = self.env['res.lang'].search([('code', '=', lc)], limit=1)
        return dl.id if dl else self.env['res.lang'].search([]).ids[0]

    def _active_languages(self):
        return self.env['res.lang'].search([]).ids

    def add_to_cart(self, partner, product_id, set_qty, add_qty, response):
        PartnerObj = self.env['res.partner'].sudo()
        Partner = PartnerObj.browse(partner)
        if Partner:
            Product = self.env['product.product'].sudo().search([('id', '=', product_id)])
            if Product:
                last_order = Partner.last_mobikul_so_id
                if last_order:
                    flag = 0
                    for line in last_order.order_line:
                        if line.product_id == Product:
                            if set_qty:
                                line.product_uom_qty = set_qty
                                line.product_uom_change()
                                line._onchange_discount()
                                flag = 1
                            elif add_qty:
                                line.product_uom_qty += int(add_qty)
                                line.product_uom_change()
                                line._onchange_discount()
                                flag = 1
                            else:
                                flag = -1
                                result = {'message': _('Insufficient data.'), 'success': False}
                    if not flag:
                        # Create order line
                        self._create_so_line(last_order, Product, int(add_qty))
                        flag = True
                    if flag == 1:
                        result = {'message': _('Added Successfully.'),
                                  'productName': Product.display_name, 'success': True}
                    result['cartCount'] = last_order.cart_count
                    return result

                else:
                    # create Order
                    local = response.get('local', {})
                    res = self._create_so(Partner, local)
                    self._create_so_line(res['order'], Product, int(add_qty))
                    result = {'message': _(
                        'Added Successfully.'), 'cartCount': res['order'].cart_count, 'productName': Product.display_name, 'success': True}
                    return result
            else:
                result = {'success': False, 'message': _('Insufficient data.')}
                return result
        else:
            result = {'success': False, 'message': _('Account not found !!!')}
            return result

    def sellerDashboardData(self, seller_Obj):
        prdObj = self.env['product.template'].sudo()
        SaleOrderLine = self.env['sale.order.line'].sudo()
        approved_count = prdObj.search_count(
            [('marketplace_seller_id', '=', seller_Obj.id), ('status', '=', 'approved')])
        pending_count = prdObj.search_count(
            [('marketplace_seller_id', '=', seller_Obj.id), ('status', '=', 'pending')])
        rejected_count = prdObj.search_count(
            [('marketplace_seller_id', '=', seller_Obj.id), ('status', '=', 'rejected')])
        new_sol_count = SaleOrderLine.search_count(
            [('marketplace_seller_id', '=', seller_Obj.id), ('marketplace_state', '=', 'new')])
        approved_sol_count = SaleOrderLine.search_count(
            [('marketplace_seller_id', '=', seller_Obj.id), ('marketplace_state', '=', 'approved')])
        shipped_sol_count = SaleOrderLine.search_count(
            [('marketplace_seller_id', '=', seller_Obj.id), ('marketplace_state', '=', 'shipped')])
        temp = {
            "approved_productCount": approved_count,
            "pending_productCount": pending_count,
            "rejected_productCount": rejected_count,
            "new_solCount": new_sol_count,
            "approved_solCount": approved_sol_count,
            "shipped_solCount": shipped_sol_count,
            "total": {
                "label": "Total Amount",
                "value": seller_Obj.total_mp_payment
            },
            "balance": {
                "label": "Balance Amount",
                "value": seller_Obj.balance_mp_payment
            },

        }
        return temp

    def _getPaymentTerms(self):
        mobikul = self.sudo().search([], limit=1)
        temp = {
            "paymentTerms": {
                "paymentShortTerms": mobikul.payment_short_terms,
                "paymentLongTerms": mobikul.payment_long_terms
            }
        }
        return temp

    def easy_date(self, time=False):
        """
        Get a datetime object or a timestamp and return a
        easy read string like 'Just now', 'Yesterday', '3 months ago',
        'Year ago'.
        """
        now = datetime.now()
        if type(time) is str:
            time = fields.Datetime.from_string(time)
        if type(time) is int:
            diff = now - datetime.fromtimestamp(time)
        elif isinstance(time, datetime):
            diff = now - time
        elif not time:
            diff = now - now
        second_diff = diff.seconds
        day_diff = diff.days

        if day_diff < 0:
            return ''

        if day_diff == 0:
            if second_diff < 10:
                return "just now"
            if second_diff < 60:
                return str(second_diff) + " seconds ago"
            if second_diff < 120:
                return "a minute ago"
            if second_diff < 3600:
                return str(int(second_diff / 60)) + " minutes ago"
            if second_diff < 7200:
                return "an hour ago"
            if second_diff < 86400:
                return str(int(second_diff / 3600)) + " hours ago"
        if day_diff == 1:
            return "Yesterday"
        if day_diff < 7:
            return str(day_diff) + " days ago"
        if day_diff < 31:
            return str(int(day_diff / 7)) + " weeks ago"
        if day_diff < 365:
            return str(int(day_diff / 30)) + " months ago"
        return str(int(day_diff / 365)) + " years ago"

    def _getdefaultWebsite_id(self):
        website_id = self.env['website'].search([], limit=1)
        return website_id.id

    name = fields.Char('Mobikul App Title', default="Mobikul App", required=1)
    salesperson_id = fields.Many2one('res.users', string='Default Salesperson')
    salesteam_id = fields.Many2one('crm.team', string='Default Sales Team')
    api_key = fields.Char(string='API Secret key', default="dummySecretKey", required=1)
    fcm_api_key = fields.Char(string='FCM Api key')
    color_scheme = fields.Selection([
        ('default', 'Default'),
        ('red-green', 'Red-Green'),
        ('light-green', 'Light Green'),
        ('deep-purple-pink', 'Deep Purple-Pink'),
        ('blue-orange', 'Blue Orange'),
        ('light-blue-red', 'Light Blue-Red')],
        string='Color Scheme', required=True,
        default='default',
        help="Color Options for your Mobikul App.")

    default_lang = fields.Many2one('res.lang', string='Default Language', default=_default_language,
                                   help="If the selected language is loaded in the mobikul, all documents related to "
                                   "this contact will be printed in this language. If not, it will be English.")

    language_ids = fields.Many2many('res.lang', 'mobikul_lang_rel',
                                    'mobikul_id', 'lang_id', 'Languages', default=_active_languages)
    pricelist_id = fields.Many2one('product.pricelist', string='Default Pricelist')
    currency_id = fields.Many2one(
        'res.currency', related='pricelist_id.currency_id', string='Default Currency', readonly=True)
    order_mail_template = fields.Many2one('mail.template', string='Confirmation Email', readonly=True,
                                          default=_default_order_mail_template, help="Email sent to customer at the end of the checkout process")
    product_limit = fields.Integer(
        default=10, string='Limit Products per page', help='Used in Pagination', required=1)
    website_id = fields.Many2one('website', default=_getdefaultWebsite_id,
                                 help="select website id for the app")
    country_ids = fields.Many2many('res.country', 'mobikul_coumtry_rel',
                                   'mobikul_id', 'country_id', string='Countries')
    enable_term_and_condition = fields.Boolean(default=False, string='Enable Terms and Condition')
    signup_terms_and_condition = fields.Html(string='Terms and Condition', translate=True)
    payment_short_terms = fields.Html(string='Payment Short Terms', required=True,
                                      default="Payment short Terms and Conditions Decription", translate=True)
    payment_long_terms = fields.Html(string='Payment Long Terms', required=True,
                                     default="Payment long Terms and Conditions Decription", translate=True)

    def unlink(self):
        raise UserError(_('You cannot remove/deactivate this Configuration.'))


class MobikulBanners(models.Model):
    _name = 'mobikul.banners'
    _description = 'Mobikul Banner Class'
    _order = "sequence, name"

    name = fields.Char('Title', required=True, translate=True)
    active = fields.Boolean(default=True)
    description = fields.Text('Description', translate=True)
    image = fields.Binary('Image', attachment=True)
    banner_action = fields.Selection([
        ('product', 'Open Product Page'),
        ('category', 'Open Category Page'),
        ('custom', 'Open Custom Collection Page'),
        ('none', 'Do nothing')],
        string='Action to be triggered', required=True,
        default='none',
        help="Define what action will be triggerred when click/touch on the banner.")
    product_id = fields.Many2one('product.template', string='Choose Product')
    category_id = fields.Many2one('mobikul.category', string='Choose Category')
    product_ids = fields.Many2many('product.template', string='Choose Products')
    url = fields.Char(
        'Image URL', help="Static URL of Banner Image, used when banner`s image is not present.")
    date_published = fields.Datetime('Publish Date')
    date_expired = fields.Datetime('Expiration Date')
    sequence = fields.Integer(default=10, help='Display order')
    total_views = fields.Integer('Total # Views', default=0, readonly=1)

    @api.model
    def create(self, values):
        if not values.get('image') and not values.get('url'):
            raise UserError(_('Please upload Banner`s Image or enter Image URL'))
        if not values.get('date_published'):
            values['date_published'] = datetime.now()
        return super(MobikulBanners, self).create(values)

    # crone for auto inactive expire banners
    @api.model
    def process_inactive_mobikul_banner(self):
        banner = self.sudo().search([])
        inactive_MobBanners = []
        for b in banner:
            if b.date_expired:
                if fields.Date.from_string(fields.Datetime.now()) > fields.Date.from_string(b.date_expired):
                    inactive_MobBanners.append(b)
        for i in inactive_MobBanners:
            i.active = False

# method to check expire banners
    @api.model
    def remove_expireBanners(self):
        banner = self.sudo().search([])
        MobBanners = []
        for b in banner:
            if b.date_expired:
                if fields.Date.from_string(fields.Datetime.now()) <= fields.Date.from_string(b.date_expired):
                    MobBanners.append(b)
            else:
                MobBanners.append(b)
        return MobBanners


class MobikulCategory(models.Model):
    _name = 'mobikul.category'
    _description = 'Mobikul Category'
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    parent_id = fields.Many2one('mobikul.category', string='Parent Category', index=True)
    child_id = fields.One2many('mobikul.category', 'parent_id', string='Children Categories')
    banner = fields.Binary('Banner', attachment=True)
    icon = fields.Binary('Icon', attachment=True)
    sequence = fields.Integer(default=10, help='Display order')
    complete_name = fields.Char(
        'Complete Name', compute='_compute_complete_name',
        store=True)
    type = fields.Selection([
        ('featured', 'Featured Category'),
        ('normal', 'Normal')], 'Category Type', default='normal',
        help="A Featured category is a category that can be used ...")
    # this field is added for mobikul category merge
    website_cat_id = fields.Many2one('product.public.category', 'Webiste Category')

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for category in self:
            if category.parent_id:
                category.complete_name = '%s / %s' % (
                    category.parent_id.complete_name, category.name)
            else:
                category.complete_name = category.name

    @api.constrains('parent_id')
    def check_parent_id(self):
        if not self._check_recursion():
            raise ValueError(_('Error ! You cannot create recursive categories.'))

    def name_get(self):
        res = []
        for category in self:
            names = [category.name]
            parent_category = category.parent_id
            while parent_category:
                names.append(parent_category.name)
                parent_category = parent_category.parent_id
            res.append((category.id, ' / '.join(reversed(names))))
        return res

    # method call from server action
    @api.model
    def sync_category(self):
        action = self.env.ref('mobikul.mobikul_sync_cat_action').read()[0]
        action['views'] = [(self.env.ref('mobikul.mobikul_sync_cat_form').id, 'form')]
        action['context'] = self._context
        return action

    # def _compute_products(self):
    #   read_group_res = self.env['product.template'].read_group([('categ_id', 'in', self.ids)], ['categ_id'], ['categ_id'])
    #   group_data = dict((data['categ_id'][0], data['categ_id_count']) for data in read_group_res)
    #   for categ in self:
    #       categ.product_count = group_data.get(categ.id, 0)


class MobikulSyncCategory(models.Model):
    _name = "mobikul.sync.category"
    _description = " Mobikul category mappings"

    sync_type = fields.Selection([
        ('name', 'Only Name'),
        ('name_seq', 'Name and Sequence'),
        ('name_parent', 'Name and Parent Category'),
        ('name_parent_seq', 'Name, Parent Category and Sequence'), ], 'Sync Type', default='name_parent_seq',
        help="Sync mobikul category on the basis of Selection")

    def show_msg_wizard(self, msg):
        partial_id = self.env['wk.wizard.message'].create({'text': msg})
        return {
            'name': "Message",
            'view_mode': 'form',
            'view_id': False,
            'view_type': 'form',
            'res_model': 'wk.wizard.message',
            'res_id': partial_id.id,
            'type': 'ir.actions.act_window',
            'nodestroy': True,
            'target': 'new',
        }

    def sync_mobikul_cat_with_web_cat(self):
        isCatMerge = self.env['ir.module.module'].sudo().search(
            [('state', '=', 'installed'), ('name', '=', 'mobikul_cat_merge')]) and True or False
        if isCatMerge:
            mobikul_catg_ids = self.env['mobikul.category'].search(
                [("id", "in", self._context.get('active_ids'))])
            if not self.sync_type:
                raise UserError(_("Please select the Sync Type."))
            for mob_cat in mobikul_catg_ids:
                if mob_cat.website_cat_id.id:
                    if self.sync_type == "name":
                        mob_cat.name = mob_cat.website_cat_id.name
                    elif self.sync_type == "name_parent":
                        mob_cat.name = mob_cat.website_cat_id.name
                        mob_cat.parent_id = mob_cat.website_cat_id.parent_id.mobikul_cat_id.id
                    elif self.sync_type == "name_parent_seq":
                        mob_cat.name = mob_cat.website_cat_id.name
                        mob_cat.parent_id = mob_cat.website_cat_id.parent_id.mobikul_cat_id.id
                        mob_cat.sequence = mob_cat.website_cat_id.sequence
                    elif self.sync_type == "name_seq":
                        mob_cat.name = mob_cat.website_cat_id.name
                        mob_cat.sequence = mob_cat.website_cat_id.sequence

                else:
                    _logger.info("MESAGE :Website category is not present in Mobikul Caegory")
            if self.sync_type == "name":
                message = "Done! name are synced with mobikul category from Website category."
            elif self.sync_type == "name_seq":
                message = "Done! name and sequence are synced with mobikul category from Website category."
            elif self.sync_type == "name_parent":
                message = "Done! name and parent category are synced with mobikul categories from Website category."
            elif self.sync_type == "name_parent_seq":
                message = "Done! name, sequence and parent category are synced with mobikul categories from Website category."
        else:
            message = "Install the Mobikul Category Merge Module First"
        return self.show_msg_wizard(message)


class MobikulPushNotificationTemplate(models.Model):
    _name = 'mobikul.push.notification.template'
    _description = 'Mobikul Push Notification Templates'
    _order = "name"

    def _addMe(self, data):
        self.env["mobikul.notification.messages"].sudo().create(data)
        return True

    def _get_key(self):
        mobikul = self.env['mobikul'].sudo().search([], limit=1)
        return mobikul and mobikul.fcm_api_key or ""

    @api.model
    def _pushMe(self, key, payload_data, data=False):
        status = True
        summary = ""
        try:
            push_service = FCMAPI(api_key=key)
            summary = push_service.send([payload_data])
            if data:
                self._addMe(data)
        except Exception as e:
            status = False
            summary = "Error: %r" % e
        return [status, summary]

    @api.model
    def _send(self, to_data, customer_id=False, max_limit=20):
        """
        to_data = dict(to or registration_ids)
        """
        if type(to_data) != dict:
            return False
        if not to_data.get("to", False) and not to_data.get("registration_ids", False):
            if not customer_id:
                return False
            reg_data = self.env['fcm.registered.devices'].sudo().search_read(
                [('customer_id', '=', customer_id)], limit=max_limit, fields=['token'])
            if not reg_data:
                return False
            to_data = {
                "registration_ids": [r['token'] for r in reg_data]
            }
        notification = dict(title=self.notification_title,
                            body=self.notification_body, sound="default")
        if self.notification_color:
            notification['color'] = self.notification_color
        if self.notification_tag:
            notification['tag'] = self.notification_tag

        fcm_payload = dict(notification=notification)
        fcm_payload.update(to_data)
        data_message = dict(type="", id="", domain="", image="", name="")

        if self.banner_action == 'product':
            data_message['type'] = 'product'
            data_message['id'] = self.product_id.id
            data_message['name'] = self.product_id.name
        elif self.banner_action == 'category':
            data_message['type'] = 'category'
            data_message['id'] = self.category_id.id
            data_message['name'] = self.category_id.name
        elif self.banner_action == 'custom':
            data_message['type'] = 'custom'
            data_message['domain'] = "[('id','in',%s)]" % self.product_ids.ids
            data_message['name'] = self.notification_title
        else:
            data_message['type'] = 'none'
        data_message['image'] = _get_image_url(self._context.get(
            'base_url'), 'mobikul.push.notification.template', self.id, 'image', self.write_date)
        data_message['notificationId'] = random.randint(1, 99999)
        fcm_payload['data'] = data_message
        if customer_id:
            data = dict(
                title=self.notification_title, body=self.notification_body, customer_id=customer_id,
                banner=self.image, datatype='default'
            )
        return self._pushMe(self._get_key(), json.dumps(fcm_payload).encode('utf8'), customer_id and data or False)

    name = fields.Char('Name', required=True, translate=True)
    notification_color = fields.Char('Color', default='PURPLE')
    notification_tag = fields.Char('Tag')
    notification_title = fields.Char('Title', required=True, translate=True)
    active = fields.Boolean(default=True, copy=False)
    notification_body = fields.Text('Body', translate=True)
    image = fields.Binary('Image', attachment=True)
    banner_action = fields.Selection([
        ('product', 'Open Product Page'),
        ('category', 'Open Category Page'),
        ('custom', 'Open Custom Collection Page'),
        ('none', 'Do nothing')],
        string='Action', required=True,
        default='none',
        help="Define what action will be triggerred when click/touch on the banner.")
    product_id = fields.Many2one('product.template', string='Choose Product')
    product_ids = fields.Many2many('product.template', string='Choose Products')
    category_id = fields.Many2one('mobikul.category', string='Choose Category')
    device_id = fields.Many2one('fcm.registered.devices', string='Select Device')
    total_views = fields.Integer('Total # Views', default=0, readonly=1, copy=False)
    condition = fields.Selection([
        ('signup', 'Customer`s SignUp'),
        ('orderplaced', "Order Placed")
    ], string='Condition', required=True, default='signup')

    def dry_run(self):
        self.ensure_one()
        to_data = dict(to=self.device_id and self.device_id.token or "")
        result = self._send(
            to_data, self.device_id and self.device_id.customer_id and self.device_id.customer_id.id or False)
        # raise UserError('Result: %r'%result)

    def copy(self, default=None):
        self.ensure_one()
        default = dict(default or {}, name=_('%s(copy)') % self.name)
        return super(MobikulPushNotificationTemplate, self).copy(default)


class MobikulPushNotification(models.Model):
    _name = 'mobikul.push.notification'
    _description = 'Mobikul Push Notification'
    _order = "activation_date, name"
    _inherit = ['mobikul.push.notification.template']

    @api.model
    def parse_n_push(self, max_limit=20, registration_ids=None):
        to_data = dict()
        if self.notification_type == 'token-auto':
            reg_data = self.env['fcm.registered.devices'].sudo(
            ).search_read(limit=max_limit, fields=['token'])
            registration_ids = [r['token'] for r in reg_data]
        elif self.notification_type == 'token-manual':
            registration_ids = [d.token for d in self.device_ids]
        elif self.notification_type == 'topic':
            to_data['to'] = '/topics/%s' % self.topic_id.name
        else:
            return [False, "Insufficient Data"]

        if registration_ids:
            if len(registration_ids) > 1:
                to_data['registration_ids'] = registration_ids
            else:
                to_data['to'] = registration_ids[0]
        return self._send(to_data)

    summary = fields.Text('Summary', readonly=True)
    activation_date = fields.Datetime('Activation Date', copy=False)
    notification_type = fields.Selection([
        ('token-auto', 'Token-Based(All Reg. Devices)'),
        ('token-manual', 'Token-Based(Selected Devices)'),
        ('topic', 'Topic-Based'),
    ],
        string='Type', required=True,
        default='token-auto')
    topic_id = fields.Many2one('fcm.registered.topics', string='Choose Topic')
    device_ids = fields.Many2many('fcm.registered.devices', string='Choose Devices/Customers')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirm', 'Confirm'),
        ('hold', 'Hold'),
        ('error', 'Error'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
    ], string='Status', readonly=True, copy=False, index=True, track_visibility='onchange', default='draft')

    def action_cancel(self):
        for record in self:
            record.state = 'cancel'
        return True

    def action_confirm(self):
        for record in self:
            record.state = 'confirm'
        return True

    def action_draft(self):
        for record in self:
            record.state = 'draft'
        return True

    def action_hold(self):
        for record in self:
            record.state = 'hold'
        return True

    def push_now(self):
        for record in self:
            response = record.parse_n_push()
            record.state = response[0] and 'done' or 'error'
            record.summary = response[1]
        return True

    def duplicate_me(self):
        self.ensure_one()
        action = self.env.ref('mobikul.mobikul_push_notification_action').read()[0]
        action['views'] = [(self.env.ref('mobikul.mobikul_push_notification_view_form').id, 'form')]
        action['res_id'] = self.copy().id
        return action


class MobikulProductSlider(models.Model):
    _name = 'mobikul.product.slider'
    _description = 'Mobikul Product Slider'
    _order = "sequence"

    def _products_count(self):
        r = {}
        for slider in self:
            slider.product_count = r.get(slider.id, len(slider.get_product_data({'count': True})))
        return r

    def action_view_products(self):
        products = self.get_product_data({'count': True})
        action = self.env.ref('mobikul.mobikul_product_template_action').read()[0]
        action['domain'] = [('id', 'in', products)]
        return action

    def get_product_data(self, context=None):
        context = context or {}
        if not 'base_url' in context:
            context['base_url'] = self.env['ir.config_parameter'].get_param('web.base.url')
        orderBy = context.get('order', None)
        mlimit = context.get('limit', self.item_limit)
        moffset = context.get('offset', 0)

        prod_obj = self.env['product.template'].sudo()
        product_filter = _get_product_domain()
        if self.product_selection == "manual":
            product_filter.append(('id', 'in', self.product_ids._ids))
        elif self.product_based_on == 'new':
            orderBy = 'id desc'
        elif self.product_based_on == 'iCategory':
            product_filter.append(
                ('categ_id', '=', self.icategory_id and self.icategory_id.id or False))
        elif self.product_based_on == 'wCategory':
            product_filter.append(
                ('public_categ_ids', '=', self.wcategory_id and self.wcategory_id.id or False))
        elif self.product_based_on == 'mCategory':
            product_filter.append(
                ('mobikul_categ_ids', '=', self.mcategory_id and self.mcategory_id.id or False))
        all_prods = prod_obj.search(product_filter, order=orderBy)
        if 'count' in context:
            return all_prods._ids
        else:
            product_data = prod_obj.search_read(
                product_filter, limit=mlimit, fields=_get_product_fields(), offset=moffset, order=orderBy)
        result = {'tcount': len(all_prods), 'offset': moffset}
        result['products'] = _getProductData(product_data, context.get('base_url'), context.get(
            'currencySymbol'), context.get('currencyPosition'), context.get('lang_obj'),context.get('discount_policy'))
        return result

    name = fields.Char('Slider Title', required=True, translate=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10, help='Display order', required=True)
    description = fields.Text('Description', translate=True)
    display_banner = fields.Boolean('Display Banner', default=False)
    banner = fields.Binary('Banner', attachment=True)
    url = fields.Char('Link URL', help="Used when someone click on banner/view-all button.")
    product_ids = fields.Many2many('product.template', string='Choose Products')
    total_views = fields.Integer('Total # Views', default=0, readonly=1)
    item_limit = fields.Integer('Maximum no. of products in a slider', default=5, required=True)
    item_display_limit = fields.Integer(
        'Display no. of Products in a slider(per row)', default=5, required=True)
    product_img_position = fields.Selection([
        ('center', 'Center'),
        ('left', 'Left'),
        ('right', 'Right'),
    ],
        string='Product Image Position', required=True,
        default='center')
    slider_mode = fields.Selection([
        ('default', 'Default(Slide)'),
        ('fixed', 'Fixed'),
    ],
        string='Slider Mode', required=True,
        default='default',
        help="Define which type of behaviour you want with your Slider.")
    product_selection = fields.Selection([
        ('manual', 'Manual'),
        ('automatic', 'Automatic'),
    ],
        string='Selection Criteria', required=True, default='automatic')
    product_based_on = fields.Selection([
        ('new', 'Newly created'),
        ('iCategory', 'Internal Category'),
        ('mCategory', 'Mobikul Category'),
        ('wCategory', 'Website Category'),
    ],
        string='Based on', default='new')
    mcategory_id = fields.Many2one('mobikul.category', string='Mobikul Category')
    wcategory_id = fields.Many2one('product.public.category', string='Website Category')
    icategory_id = fields.Many2one('product.category', string='Internal Category')
    product_count = fields.Integer(compute='_products_count', string='# Products')
    bk_color = fields.Char('Background Color')


class FcmRegisteredDevices(models.Model):
    _name = 'fcm.registered.devices'
    _description = 'All Registered Devices on FCM for Push Notifications.'
    _order = 'write_date desc'

    def name_get(self):
        res = []
        for record in self:
            name = record.customer_id and record.customer_id.name or ''
            res.append((record.id, "%s(DeviceId:%s)" % (name, record.device_id)))
        return res

    name = fields.Char('Name')
    token = fields.Text('FCM Registration ID', readonly=True)
    device_id = fields.Char('Device Id', readonly=True)
    customer_id = fields.Many2one('res.partner', string="Customer", readonly=True, index=True)
    active = fields.Boolean(default=True, readonly=True)
    # write_date = fields.Datetime(string='Last Update', readonly=True, help="Date on which this entry is created.")
    description = fields.Text('Description', readonly=True)


class FcmRegisteredTopics(models.Model):
    _name = 'fcm.registered.topics'
    _description = 'All Registered Topics for Push Notifications.'

    name = fields.Char('Topic Name', required=True)


class MobikulNotificationMessages(models.Model):
    _name = 'mobikul.notification.messages'
    _description = 'Mobikul Notification Messages'

    name = fields.Char('Message Name', default='/', index=True, copy=False, readonly=True)
    title = fields.Char('Title')
    subtitle = fields.Char('Subtitle')
    body = fields.Text('Body')
    icon = fields.Binary('Icon')
    banner = fields.Binary('Banner')
    is_read = fields.Boolean('Is Read', default=False, readonly=True)
    customer_id = fields.Many2one('res.partner', string="Customer", index=True)
    active = fields.Boolean(default=True, readonly=True)
    period = fields.Char('Period', compute='_compute_period')
    datatype = fields.Selection([
        ('default', 'Default'),
        ('order', 'Order')],
        string='Data Type', required=True,
        default='default',
        help="Notification Messages Data Type for your Mobikul App.")

    @api.model
    def create(self, vals):
        vals['name'] = self.env['ir.sequence'].next_by_code('mobikul.notification.messages')
        return super(MobikulNotificationMessages, self).create(vals)

    def _compute_period(self):
        for i in self:
            i.period = self.env['mobikul'].easy_date(i.create_date)
