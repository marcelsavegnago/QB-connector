# -*- coding: utf-8 -*-
import base64
import json
import logging
from datetime import datetime, timedelta

import requests
import xmltodict
from xmltodict import ParsingInterrupted

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = "res.company"

    @api.model
    def convert_xmltodict(self, response):
        """Return dictionary object"""
        try:
            # convert xml response to OrderedDict collections, return collections.OrderedDict type
            order_dict = xmltodict.parse(response)
        except ParsingInterrupted as e:
            _logger.error(e)
            raise e
        # convert OrderedDict to regular dictionary object
        response_dict = json.loads(json.dumps(order_dict))
        return response_dict

    # Company level QuickBooks Configuration fields
    client_id = fields.Char('Client Id', copy=False, help="The client ID you obtain from the developer dashboard.")
    client_secret = fields.Char('Client Secret', copy=False, help="The client secret you obtain from the developer dashboard.")

    auth_base_url = fields.Char('Authorization URL', default="https://appcenter.intuit.com/connect/oauth2", help="User authenticate uri")
    access_token_url = fields.Char('Authorization Token URL', default="https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
                                   help="Exchange code for refresh and access tokens")
    request_token_url = fields.Char('Redirect URL', default="http://localhost:5000/get_auth_code",
                                    help="One of the redirect URIs listed for this project in the developer dashboard.")
    url = fields.Char('API URL', default="https://sandbox-quickbooks.api.intuit.com/v3/company/",
                      help="Intuit API URIs, use access token to call Intuit API's")

    # used for api calling, generated during authorization process.
    realm_id = fields.Char('Company Id/ Realm Id', copy=False, help="A unique company Id returned from QBO")
    auth_code = fields.Char('Auth Code', copy=False, help="An authenticated code")
    access_token = fields.Char('Access Token', copy=False,
                               help="The token that must be used to access the QuickBooks API. Access token expires in 3600 seconds.")
    minorversion = fields.Char('Minor Version', copy=False, default="8", help="QuickBooks minor version information, used in API calls.")
    access_token_expire_in = fields.Datetime('Access Token Expire In', copy=False, help="Access token expire time.")
    qbo_refresh_token = fields.Char('Refresh Token', copy=False,
                                    help="The token that must be used to access the QuickBooks API. Refresh token expires in 8726400 seconds.")
    refresh_token_expire_in = fields.Datetime('Refresh Token Expire In', copy=False, help="Refresh token expire time.")

    #     '''  Tracking Fields for Customer'''
    #     x_quickbooks_last_customer_sync = fields.Datetime('Last Synced On', copy=False,)
    #     x_quickbooks_last_customer_imported_id = fields.Integer('Last Imported ID', copy=False,)
    '''  Tracking Fields for Account'''
    last_customer_imported_id = fields.Char('Last Imported Customer Id', copy=False, default=0)
    last_acc_imported_id = fields.Char('Last Imported Account Id', copy=False, default=0)
    last_imported_tax_id = fields.Char('Last Imported Tax Id', copy=False, default=0)
    last_imported_tax_agency_id = fields.Char('Last Imported Tax Agency Id', copy=False, default=0)
    last_imported_product_category_id = fields.Char('Last Imported Product Category Id', copy=False, default=0)
    last_imported_product_id = fields.Char('Last Imported Product Id', copy=False, default=0)
    last_imported_customer_id = fields.Char('Last Imported Customer Id', copy=False, default=0)
    last_imported_vendor_id = fields.Char('Last Imported Vendor Id', copy=False, default=0)
    last_imported_payment_method_id = fields.Char('Last Imported Payment Method Id', copy=False, default=0)
    last_imported_payment_id = fields.Char('Last Imported Payment Id', copy=False, default=0)
    last_imported_bill_payment_id = fields.Char('Last Imported Bill Payment Id', copy=False, default=0)

    '''  Tracking Fields for Payment Term'''
    x_quickbooks_last_paymentterm_sync = fields.Datetime('Last Synced On', copy=False)
    x_quickbooks_last_paymentterm_imported_id = fields.Integer('Last Imported ID', copy=False)

    @api.multi
    def login(self):

        url = self.auth_base_url + '?client_id=' + self.client_id + '&scope=com.intuit.quickbooks.accounting&redirect_uri=' + self.request_token_url + '&response_type=code&state=abccc'
        return {
            "type": "ir.actions.act_url",
            "url": url,
            "target": "new"
        }

    @api.model
    def _run_refresh_token(self, **kwag):
        self.refresh_token()

    @api.multi
    def refresh_token(self):
        """Get new access token from existing refresh token"""
        quickbook_id = self.env['res.users'].search([('id', '=', self.env.uid)], limit=1).company_id
        if quickbook_id:

            client_id = quickbook_id.client_id
            client_secret = quickbook_id.client_secret

            raw_b64 = str(client_id + ":" + client_secret)

            raw_b64 = raw_b64.encode('utf-8')
            converted_b64 = base64.b64encode(raw_b64).decode('utf-8')
            auth_header = 'Basic ' + converted_b64
            headers = {}
            headers['Authorization'] = str(auth_header)
            headers['accept'] = 'application/json'
            payload = {'grant_type': 'refresh_token', 'refresh_token': quickbook_id.qbo_refresh_token}

            access_token = requests.post(quickbook_id.access_token_url, data=payload, headers=headers)
            if access_token:
                parsed_token_response = json.loads(access_token.text)
                if parsed_token_response:
                    quickbook_id.write({
                        'access_token': parsed_token_response.get('access_token'),
                        'qbo_refresh_token': parsed_token_response.get('refresh_token'),
                        'access_token_expire_in': datetime.now() + timedelta(seconds=parsed_token_response.get('expires_in')),
                        'refresh_token_expire_in': datetime.now() + timedelta(seconds=parsed_token_response.get('x_refresh_token_expires_in'))
                    })
                    _logger.info(_("Token refreshed successfully!"))

    @api.model
    def get_import_query_url(self):
        if self.access_token:
            headers = {}
            headers['Authorization'] = 'Bearer ' + str(self.access_token)
            headers['accept'] = 'application/json'
            headers['Content-Type'] = 'text/plain'
            if self.url:
                url = str(self.url) + str(self.realm_id)
            else:
                raise ValidationError(_('Url not configure'))
            return {'url': url, 'headers': headers, 'minorversion': self.minorversion}
        else:
            raise ValidationError(_('Invalid access token'))

    @api.multi
    def import_customers(self):
        self.ensure_one()
        query = "select * from Customer WHERE Id > '%s' order by Id" % (self.last_imported_customer_id)
        url_str = self.get_import_query_url()
        url = url_str.get('url') + '/query?%squery=%s' % (
            'minorversion=' + url_str.get('minorversion') + '&' if url_str.get('minorversion') else '', query)
        data = requests.request('GET', url, headers=url_str.get('headers'))
        if data:
            partner = self.env['res.partner'].create_partner(data, is_customer=True)
            if partner:
                self.last_imported_customer_id = partner.qbo_customer_id
        else:
            _logger.warning(_('Empty data'))

    @api.multi
    def import_vendors(self):
        self.ensure_one()
        query = "select * from vendor WHERE Id > '%s' order by Id" % (self.last_imported_vendor_id)
        url_str = self.get_import_query_url()
        url = url_str.get('url') + '/query?%squery=%s' % (
            'minorversion=' + url_str.get('minorversion') + '&' if url_str.get('minorversion') else '', query)
        data = requests.request('GET', url, headers=url_str.get('headers'))
        if data:
            partner = self.env['res.partner'].create_partner(data, is_vendor=True)
            if partner:
                self.last_imported_vendor_id = partner.qbo_vendor_id
        else:
            _logger.warning(_('Empty data'))

    @api.multi
    def import_chart_of_accounts(self):
        self.ensure_one()
        query = "select * from Account WHERE Id > '%s' order by Id" % (self.last_acc_imported_id)
        url_str = self.get_import_query_url()
        url = url_str.get('url') + '/query?query=' + query
        data = requests.request('GET', url, headers=url_str.get('headers'))
        if data:
            acc = self.env['account.account'].create_account_account(data)
            if acc:
                self.last_acc_imported_id = acc.qbo_id
        else:
            _logger.warning(_('Empty data'))

    @api.multi
    def import_tax(self):
        self.ensure_one()
        query = "select * From TaxCode WHERE Id > '%s' order by Id" % (self.last_imported_tax_id)
        url_str = self.get_import_query_url()
        url = url_str.get('url') + '/query?query=' + query
        data = requests.request('GET', url, headers=url_str.get('headers'))
        if data:
            acc_tax = self.env['account.tax'].create_account_tax(data)
            if acc_tax:
                self.last_imported_tax_id = acc_tax.qbo_tax_id or acc_tax.qbo_tax_rate_id
        else:
            _logger.warning(_('Empty data'))

    @api.multi
    def import_tax_agency(self):
        self.ensure_one()
        query = "select * From TaxAgency WHERE Id > '%s' order by Id" % (self.last_imported_tax_agency_id)
        url_str = self.get_import_query_url()
        url = url_str.get('url') + '/query?query=' + query
        data = requests.request('GET', url, headers=url_str.get('headers'))
        if data:
            agency = self.env['account.tax.agency'].create_account_tax_agency(data)
            if agency:
                self.last_imported_tax_agency_id = agency.qbo_agency_id
        else:
            _logger.warning(_('Empty data'))

    @api.multi
    def import_product_category(self):
        self.ensure_one()
        query = "select * from Item where Type='Category' AND Id > '%s' order by Id" % (self.last_imported_product_category_id)
        url_str = self.get_import_query_url()
        url = url_str.get('url') + '/query?%squery=%s' % (
            'minorversion=' + url_str.get('minorversion') + '&' if url_str.get('minorversion') else '', query)
        data = requests.request('GET', url, headers=url_str.get('headers'))
        if data:
            category = self.env['product.category'].create_product_category(data)
            if category:
                self.last_imported_product_category_id = category.qbo_product_category_id
        else:
            _logger.warning(_('Empty data'))

    @api.multi
    def import_product(self):
        self.ensure_one()
        query = "select * from Item where Id > '%s' order by Id" % (self.last_imported_product_id)
        url_str = self.get_import_query_url()
        url = url_str.get('url') + '/query?%squery=%s' % (
            'minorversion=' + url_str.get('minorversion') + '&' if url_str.get('minorversion') else '', query)
        data = requests.request('GET', url, headers=url_str.get('headers'))
        if data:
            product = self.env['product.template'].create_product(data)
            if product:
                self.last_imported_product_id = product.qbo_product_id
        else:
            _logger.warning(_('Empty data'))

    @api.multi
    def import_inventory(self):

        self.ensure_one()
        try:
            query = "select * from Item"
            url_str = self.get_import_query_url()
            url = url_str.get('url') + '/query?%squery=%s' % (
                'minorversion=' + url_str.get('minorversion') + '&' if url_str.get('minorversion') else '', query)
            data = requests.request('GET', url, headers=url_str.get('headers'))
            parsed_data = data.json()
            for recs in parsed_data.get("QueryResponse").get('Item'):
                product_exists = self.env['product.product'].search([('qbo_product_id', '=', recs.get('Id'))])
                if product_exists and product_exists.type == 'product':
                    if product_exists.qty_available != recs.get('QtyOnHand') and recs.get('QtyOnHand') >= 0:
                        #                         product_product_id = self.env['product.product'].search([('product_tmpl_id','=',product_exists.id)]).id
                        stock_qty = self.env['stock.quant'].search([('product_id', '=', product_exists.id)])
                        stock_change_qty = self.env['stock.change.product.qty']
                        vals = {
                            'product_id': product_exists.id,
                            'new_quantity': recs.get('QtyOnHand'),
                        }

                        res = stock_change_qty.create(vals)
                        res.change_product_qty()
                        #                         stock_inventory = self.env['stock.inventory'].search([('product_id','=',product_product_id)])
                        #                         res2 = stock_inventory.write({
                        #                                               'name':"INV:" +product_exists.name+"(QBO Inventory Updated)",
                        #                                               })
        except Exception as e:
            raise ValidationError(_('Inventory Update Failed due to %s' % str(e)))

    @api.multi
    def import_payment_method(self):
        self.ensure_one()
        query = "select * From PaymentMethod WHERE Id > '%s' order by Id" % (self.last_imported_payment_method_id)
        url_str = self.get_import_query_url()
        url = url_str.get('url') + '/query?%squery=%s' % (
            'minorversion=' + url_str.get('minorversion') + '&' if url_str.get('minorversion') else '', query)
        data = requests.request('GET', url, headers=url_str.get('headers'))
        if data:
            method = self.env['qbo.payment.method'].create_payment_method(data)
            if method:
                self.last_imported_payment_method_id = method.qbo_method_id
        else:
            _logger.warning(_('Empty data'))

    @api.multi
    def import_payment(self):
        self.ensure_one()
        query = "select * From Payment WHERE Id > '%s' order by Id" % (self.last_imported_payment_id)
        url_str = self.get_import_query_url()
        url = url_str.get('url') + '/query?%squery=%s' % (
            'minorversion=' + url_str.get('minorversion') + '&' if url_str.get('minorversion') else '', query)
        data = requests.request('GET', url, headers=url_str.get('headers'))
        if data:
            payment = self.env['account.payment'].create_payment(data, is_customer=True)
            if payment:
                self.last_imported_payment_id = payment.qbo_payment_id
        else:
            _logger.warning(_('Empty data'))

    @api.multi
    def import_bill_payment(self):
        self.ensure_one()
        query = "select * From billpayment WHERE Id > '%s' order by Id" % (self.last_imported_bill_payment_id)
        url_str = self.get_import_query_url()
        url = url_str.get('url') + '/query?%squery=%s' % (
            'minorversion=' + url_str.get('minorversion') + '&' if url_str.get('minorversion') else '', query)
        data = requests.request('GET', url, headers=url_str.get('headers'))
        if data:
            payment = self.env['account.payment'].create_payment(data, is_vendor=True)
            if payment:
                self.last_imported_bill_payment_id = payment.qbo_bill_payment_id
        else:
            _logger.warning(_('Empty data'))

    def import_payment_term_from_quickbooks(self):

        payment_term = self.env['account.payment.term']

        payment_term_line = self.env['account.payment.term.line']

        if self.access_token:
            headers = {}
            headers['Authorization'] = 'Bearer ' + str(self.access_token)
            headers['Accept'] = 'application/json'
            headers['Content-Type'] = 'text/plain'
            data = requests.request('GET', self.url + str(self.realm_id) + "/query?query=select * from term where Id > '{}'".format(
                str(self.x_quickbooks_last_paymentterm_imported_id)), headers=headers)
            if data:
                ''' Holds quickbookIds which are inserted '''
                recs = []

                parsed_data = json.loads(str(data.text))
                if parsed_data:
                    if parsed_data.get('QueryResponse') and parsed_data.get('QueryResponse').get('Term'):
                        for term in parsed_data.get('QueryResponse').get('Term'):
                            dict = {}
                            dict_ptl = {}
                            exists = payment_term.search([('name', '=', term.get('Name'))])
                            if not exists:
                                ''' Loop and create Data '''
                                if term.get('Active'):
                                    dict['active'] = term.get('Active')
                                if term.get('Name'):
                                    dict['note'] = term.get('Name')
                                    dict['name'] = term.get('Name')
                                '''  Insert data in account payment term line and attach its id to payment term create'''
                                if term.get('DueDays'):
                                    dict_ptl['value'] = 'balance'
                                    dict_ptl['days'] = term.get('DueDays')
                                payment_term_create = payment_term.create(dict)
                                if payment_term_create:
                                    payment_term_create.x_quickbooks_id = term.get('Id')
                                    recs.append(term.get('Id'))
                                    #                                     self.x_quickbooks_last_paymentterm_imported_id = term.get('Id')
                                    self.x_quickbooks_last_paymentterm_sync = fields.datetime.now()

                                    dict_ptl['payment_id'] = payment_term_create.id
                                    payment_term_line_create = payment_term_line.create(dict_ptl)
                                    if payment_term_line_create:
                                        _logger.info(_("Payment term line was created %s" % payment_term_line_create.id))

                            else:
                                _logger.info(_("REC Exists %s" % term.get('Name')))
                            if recs:
                                self.x_quickbooks_last_paymentterm_imported_id = max(recs)

                                #     def createOdooParentId(self, quickbook_id):


# if quickbook_id:
#             ''' GET DICTIONARY FROM QUICKBOOKS FOR CREATING A DICT '''
#             if self.access_token:
#                 headers = {}
#                 headers['Authorization'] = 'Bearer '+str(self.access_token)
#                 headers['accept'] = 'application/json'
#                 headers['Content-Type']='text/plain'
#                 print "New header is :",headers
#             data = requests.request('GET',self.url+str(self.realm_id)+'/customer/'+str(quickbook_id),headers=headers)
#             if data:
#                 parsed_data = json.loads(str(data.text))
#                 cust = parsed_data.get('Customer')
#                 if cust:
#                     print "CCCCCCCCCC", cust
# #                     if int(cust.get('Id')) > self.x_quickbooks_last_customer_imported_id:
#                     print cust.get('Id'),"\n ------------------------------------------------"
#                     ''' Check if the Id from Quickbook is present in odoo or not if present
#                     then dont insert, This will avoid duplications'''
#                     res_partner = self.env['res.partner'].search([('display_name','=',cust.get('DisplayName'))],limit=1)
#                     
#                     print "RRRRRRRRRRRR", res_partner
#                     if res_partner:
#                         return res_partner.id
#                     if not res_partner:
#                         print "Inside res_partner !!!!!!!!!!!!!"
#                         dict = {}
#                         if cust.get('PrimaryPhone'):
#                             dict['phone'] = cust.get('PrimaryPhone').get('FreeFormNumber')
#                         if cust.get('PrimaryEmailAddr'):
#                             dict['email'] = cust.get('PrimaryEmailAddr').get('Address', ' ')
#                         if cust.get('GivenName') and cust.get('FamilyName',' '):
#                             dict['name'] = cust.get('GivenName')+" "+cust.get('FamilyName',' ')
#                         if cust.get('GivenName') and not cust.get('FamilyName'):
#                             dict['name'] = cust.get('GivenName')
#                         if cust.get('FamilyName') and not cust.get('GivenName'):
#                             dict['name'] = cust.get('FamilyName')
#                         if not cust.get('FamilyName') and not cust.get('GivenName'):
#                             if cust.get('CompanyName'):
#                                 dict['name'] = cust.get('CompanyName')
#                             
# #                             if cust.get('Active'):
# #                                 if str(cust.get('Active')) == 'true':
# #                                     dict['active']=True
# #                                 else:
# #                                     dict['active']=False
#                         if cust.get('Id'):
#                             dict['x_quickbooks_id'] = cust.get('Id')
#                         if cust.get('Notes'):
#                             dict['comment'] = cust.get('Notes')
#                         if cust.get('BillWithParent'):
#                             dict['company_type'] = 'company'
#                         if cust.get('Mobile'):
#                             dict['mobile'] = cust.get('Mobile').get('FreeFormNumber')
#                         if cust.get('Fax'):
#                             dict['fax'] = cust.get('Fax').get('FreeFormNumber')
#                         if cust.get('WebAddr'):
#                             dict['website'] = cust.get('WebAddr').get('URI')
#                         if cust.get('Title'):
#                             ''' If Title is present then first check in odoo if title exists or not
#                             if exists attach Id of tile else create new and attach its ID'''
#                             dict['title'] = self.attachCustomerTitle(cust.get('Title'))
# #                                 print "FINAL DICT TITLE IS :",dict['name'],dict['title']
# #                                 aaaaaaaaaa
#                         dict['company_type']='company'
#                         print "DICT TO ENTER IS : {}".format(dict)
#                         create = res_partner.create(dict)
#                         if create:
#                             if cust.get('BillAddr'):
#                                 ''' Getting BillAddr from quickbooks and Checking 
#                                     in odoo to get countryId, stateId and create
#                                     state if not exists in odoo
#                                     ''' 
#                                 dict = {}
#                                 ''' 
#                                 Get state id if exists else create new state and return it
#                                 '''
#                                 if cust.get('BillAddr').get('CountrySubDivisionCode'):
#                                     state_id = self.attachCustomerState(cust.get('BillAddr').get('CountrySubDivisionCode'),cust.get('BillAddr').get('Country'))
#                                     if state_id:
#                                         dict['state_id'] = state_id
#                                     print "STATE ID IS ::::::::::",state_id
#                                     
#                                 country_id = self.env['res.country'].search([
#                                                                         ('name','=',cust.get('BillAddr').get('Country'))],limit=1)
#                                 if country_id:
#                                     dict['country_id'] = country_id.id
#                                 dict['parent_id'] = create.id
#                                 dict['type'] = 'invoice'
#                                 dict['zip'] = cust.get('BillAddr').get('PostalCode',' ')
#                                 dict['city'] = cust.get('BillAddr').get('City')
#                                 dict['street'] = cust.get('BillAddr').get('Line1')
#                                 print "DICT IS ",dict
#                                 child_create = res_partner.create(dict)
#                                 if child_create:
#                                     print "Child Created BillAddr"
#                             if cust.get('ShipAddr'):
#                                 ''' Getting BillAddr from quickbooks and Checking 
#                                     in odoo to get countryId, stateId and create
#                                     state if not exists in odoo
#                                     ''' 
#                                 dict = {}
#                                 if cust.get('ShipAddr').get('CountrySubDivisionCode'):
#                                     state_id = self.attachCustomerState(cust.get('ShipAddr').get('CountrySubDivisionCode'),cust.get('ShipAddr').get('Country'))
#                                     if state_id:
#                                         dict['state_id'] = state_id
#                                     print "STATE ID IS ::::::::::",state_id
#                                     
#                                     
#                                 country_id = self.env['res.country'].search([('name','=',cust.get('ShipAddr').get('Country'))])
#                                 if country_id:
#                                     dict['country_id'] = country_id[0].id
#                                 dict['parent_id'] = create.id
#                                 dict['type'] = 'delivery'
#                                 dict['zip'] = cust.get('ShipAddr').get('PostalCode',' ')
#                                 dict['city'] = cust.get('ShipAddr').get('City')
#                                 dict['street'] = cust.get('ShipAddr').get('Line1')
#                                 print "DICT IS ",dict
#                                 child_create = res_partner.create(dict)
#                                 if child_create:
#                                     print "Child Created ShipAddr"
#                                 print "Created Parent"
#                                 self.x_quickbooks_last_customer_sync = fields.Datetime.now()
#                                 self.x_quickbooks_last_customer_imported_id = int(cust.get('Id'))
#                             return create.id
# 
#     def attachCustomerTitle(self, title):
#         res_partner_tile = self.env['res.partner.title']
#         title_id = False
#         if title:
#             title_id = res_partner_tile.search([('name', '=', title)], limit=1)
#             if not title_id:
#                 ''' Create New Title in Odoo '''
#                 create_id = res_partner_tile.create({'name': title})
#                 create_id = title_id.id
#                 if create_id:
#                     return create_id.id
#         print "TITLE IS LLLLLLLLLLLLLL",title_id
#         return title_id.id
#     
#     def attachCustomerState(self, state, country):
#         res_partner_country = self.env['res.country']
#         res_partner_state = self.env['res.country.state']
#         state_id = False
#         if state and country:
#             country_id = res_partner_country.search([('name','=',country)],limit=1)
#             if country_id:
#                 print "Country Id is ::",country_id.name,country_id.id
#                 state_id = res_partner_state.search([('name','=',state)],limit=1)
#                 print "STATE ID ::::::::::::::::",state_id.country_id.id,country_id[0].id
#                 if state_id and state_id[0].country_id.id == country_id[0].id:
#                     print "Found State_id ",state_id
#                     return state_id[0].id
#                 else:
#                     print "Inside Else"
#                     ''' Create New State Under Country Id '''
#                     new_state_id = res_partner_state.create({
#                         'country_id':country_id[0].id,
#                         'code':state[:2],
#                         'name':state
#                         })
#                     if new_state_id:
#                         print "Created new State id",new_state_id
#                         return new_state_id.id
# 
#     @api.multi
#     def importcust(self):
#         if self.access_token:
#             headers = {}
#             headers['Authorization'] = 'Bearer '+str(self.access_token)
#             headers['accept'] = 'application/json'
#             headers['Content-Type']='text/plain'
#             print "New header is :",headers
#             data = requests.request('GET',self.url+str(self.realm_id)+"/query?query=select * from customer where Id > '{}'".format(self.x_quickbooks_last_customer_imported_id),headers=headers)
#             if data:
#                 recs = []
#                 parsed_data = json.loads(str(data.text))
#                 if parsed_data:
#                     print "\n\n =======Ress====== ", parsed_data,type(parsed_data)
#                     if parsed_data.get('QueryResponse') and parsed_data.get('QueryResponse').get('Customer'):
#                         for cust in parsed_data.get('QueryResponse').get('Customer'):
#         #                     if int(cust.get('Id')) > self.x_quickbooks_last_customer_imported_id:
#                             print cust.get('Id'),"\n ------------------------------------------------"
#                             ''' Check if the Id from Quickbook is present in odoo or not if present
#                             then dont insert, This will avoid duplications'''
#                             res_partner = self.env['res.partner'].search([('x_quickbooks_id','=',int(cust.get('Id')))])
#                             if not res_partner:
#                                 dict = {}
#                                 if cust.get('PrimaryPhone'):
#                                     dict['phone'] = cust.get('PrimaryPhone').get('FreeFormNumber')
#                                 if cust.get('PrimaryEmailAddr'):
#                                     dict['email'] = cust.get('PrimaryEmailAddr').get('Address', ' ')
#                                 if cust.get('GivenName') and cust.get('FamilyName',' '):
#                                     dict['name'] = cust.get('GivenName')+" "+cust.get('FamilyName',' ')
#                                 if cust.get('GivenName') and not cust.get('FamilyName'):
#                                     dict['name'] = cust.get('GivenName')
#                                 if cust.get('FamilyName') and not cust.get('GivenName'):
#                                     dict['name'] = cust.get('FamilyName')
#                                 if not cust.get('FamilyName') and not cust.get('GivenName'):
#                                     if cust.get('CompanyName'):
#                                         dict['name'] = cust.get('CompanyName')
#                                         print "Came here"
#                                     
#         #                             if cust.get('Active'):
#         #                                 if str(cust.get('Active')) == 'true':
#         #                                     dict['active']=True
#         #                                 else:
#         #                                     dict['active']=False
#                                 if cust.get('ParentRef'):
#                                     print "GOT PARENT REF",cust.get('ParentRef')
#                                     result = self.createOdooParentId(cust.get('ParentRef').get('value'))
#                                     if result:
#                                         dict['parent_id'] = result
#                                         print "ATTACHED PARENT ID"
#                                         
#                                 if cust.get('Id'):
#                                     dict['x_quickbooks_id'] = cust.get('Id')
#                                 if cust.get('Notes'):
#                                     dict['comment'] = cust.get('Notes')
#                                 if cust.get('BillWithParent'):
#                                     dict['company_type'] = 'company'
#                                 if cust.get('Mobile'):
#                                     dict['mobile'] = cust.get('Mobile').get('FreeFormNumber')
#                                 if cust.get('Fax'):
#                                     dict['fax'] = cust.get('Fax').get('FreeFormNumber')
#                                 if cust.get('WebAddr'):
#                                     dict['website'] = cust.get('WebAddr').get('URI')
#                                 if cust.get('Title'):
#                                     
#                                     ''' If Title is present then first check in odoo if title exists or not
#                                     if exists attach Id of tile else create new and attach its ID'''
#                                     dict['title'] = self.attachCustomerTitle(cust.get('Title'))
#         #                                 print "FINAL DICT TITLE IS :",dict['name'],dict['title']
#         #                                 aaaaaaaaaa
#                                 print "DICT TO ENTER IS : {}".format(dict)
#                                 create = res_partner.create(dict)
#                                 if create:
#                                     recs.append(create.id)
#                                     if not cust.get('ParentRef'):
#                                         if cust.get('BillAddr'):
#                                             ''' Getting BillAddr from quickbooks and Checking 
#                                                 in odoo to get countryId, stateId and create
#                                                 state if not exists in odoo
#                                                 ''' 
#                                             dict = {}
#                                             ''' 
#                                             Get state id if exists else create new state and return it
#                                             '''
#                                             if cust.get('BillAddr').get('CountrySubDivisionCode'):
#                                                 state_id = self.attachCustomerState(cust.get('BillAddr').get('CountrySubDivisionCode'),cust.get('BillAddr').get('Country'))
#                                                 if state_id:
#                                                     dict['state_id'] = state_id
#                                                 print "STATE ID IS ::::::::::",state_id
#                                                 
#                                             country_id = self.env['res.country'].search([
#                                                                                     ('name','=',cust.get('BillAddr').get('Country'))],limit=1)
#                                             if country_id:
#                                                 dict['country_id'] = country_id.id
#                                             dict['parent_id'] = create.id
#                                             dict['type'] = 'invoice'
#                                             dict['zip'] = cust.get('BillAddr').get('PostalCode',' ')
#                                             dict['city'] = cust.get('BillAddr').get('City')
#                                             dict['street'] = cust.get('BillAddr').get('Line1')
#                                             print "DICT IS ",dict
#                                             child_create = res_partner.create(dict)
#                                             if child_create:
#                                                 print "Child Created BillAddr"
#                                                 
#                                         if cust.get('ShipAddr'):
#                                             ''' Getting BillAddr from quickbooks and Checking 
#                                                 in odoo to get countryId, stateId and create
#                                                 state if not exists in odoo
#                                                 ''' 
#                                             dict = {}
#                                             if cust.get('ShipAddr').get('CountrySubDivisionCode'):
#                                                 state_id = self.attachCustomerState(cust.get('ShipAddr').get('CountrySubDivisionCode'),cust.get('ShipAddr').get('Country'))
#                                                 if state_id:
#                                                     dict['state_id'] = state_id
#                                                 print "STATE ID IS ::::::::::",state_id
#                                                 
#                                                 
#                                             country_id = self.env['res.country'].search([('name','=',cust.get('ShipAddr').get('Country'))])
#                                             if country_id:
#                                                 dict['country_id'] = country_id[0].id
#                                             dict['parent_id'] = create.id
#                                             dict['type'] = 'delivery'
#                                             dict['zip'] = cust.get('ShipAddr').get('PostalCode',' ')
#                                             dict['city'] = cust.get('ShipAddr').get('City')
#                                             dict['street'] = cust.get('ShipAddr').get('Line1')
#                                             print "DICT IS ",dict
#                                             child_create = res_partner.create(dict)
#                                             if child_create:
#                                                 print "Child Created ShipAddr"
#                                     print "Created Res partner"
#                                     self.x_quickbooks_last_customer_sync = fields.Datetime.now()
#                                     if recs:
#                                         self.x_quickbooks_last_customer_imported_id = max(recs)
#                                 else:
#                                     dict = {}
#                                     if cust.get('PrimayPhone'):
#                                         dict['phone'] = cust.get('PrimaryPhone').get('FreeFormNumber',' ')
#                                         
#                                     if cust.get('PrimaryEmailAddr'):
#                                         dict['email'] = cust.get('PrimaryEmailAddr').get('Address', ' ')
#                                     write = res_partner.write(dict)
#                                     if write :
#                                         print "Written Successfully"
#             else:
#                 print "Didnt got Data"
ResCompany()

# class stock_change_product_qty(models.TransientModel):
#     _inherit = "stock.change.product.qty"
#     _description = "Change Product Quantity"
#      
#     def change_product_qty(self):
#         """ Changes the Product Quantity by making a Physical Inventory. """
# #         if self._context is None:
# #             self.context = {}
#  
#         inventory_obj = self.pool.get('stock.inventory')
#         inventory_line_obj = self.pool.get('stock.inventory.line')
#  
#         for data in self.browse(self._ids):
#             if data.new_quantity < 0:
#                 raise UserError(_('Quantity cannot be negative.'))
#             ctx = self._context.copy()
#             ctx['location'] = data.location_id.id
#             ctx['lot_id'] = data.lot_id.id
#             if data.product_id.id and data.lot_id.id:
#                 filter = 'none'
#             elif data.product_id.id:
#                 filter = 'product'
#             else:
#                 filter = 'none'
#             inventory_id = inventory_obj.create({
#                 'name': _('INV: %s') % tools.ustr(data.product_id.name),
#                 'filter': filter,
#                 'product_id': data.product_id.id,
#                 'location_id': data.location_id.id,
#                 'lot_id': data.lot_id.id})
#             product = data.product_id.with_context(location=data.location_id.id, lot_id= data.lot_id.id)
#             th_qty = product.qty_available
#             print "\n\n\n data.new_qunatity -----",data.new_quantity
#             line_data = {
#                 'inventory_id': inventory_id,
#                 'product_qty': data.new_quantity,
#                 'location_id': data.location_id.id,
#                 'product_id': data.product_id.id,
#                 'product_uom_id': data.product_id.uom_id.id,
#                 'theoretical_qty': th_qty,
#                 'prod_lot_id': data.lot_id.id
#             }
#             inventory_line_obj.create(line_data)
#             inventory_obj.action_done([inventory_id])
#         return {}
#  
#
