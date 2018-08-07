from odoo import api, fields, models, _
import requests
import json
from openerp.exceptions import UserError, ValidationError
import logging
_logger = logging.getLogger(__name__)


class ResCountry(models.Model):
    _inherit = "res.country"

    @api.model
    def get_country_ref(self, country_name):
        """
        This method take country name as an argument and return county id
        :param country_name: name of the country
        :rtype int: return a recordset id
        """
        country = self.search([('name', '=', country_name)], limit=1)
        if not country:
            country = self.create({'name': country_name})
        return country.id

ResCountry()


class ResCountryState(models.Model):
    _inherit = "res.country.state"

    @api.model
    def get_state_ref(self, state_name, country_name):
        """
        This method take state name as an argument and return state id
        :param state_name: name of state
        :param country_name: name of country
        :rtype int: return a recordset id
        """
        if country_name:
            country_id = self.env['res.country'].get_country_ref(country_name)
            state = self.search([('name', '=', state_name), ('country_id', '=', country_id)], limit=1)
            if not state:
                state = self.create({'name': state_name, 'country_id': country_id, 'code': state_name})
            return state.id
        else:
            return False

ResCountryState()


class ResPartner(models.Model):
    _inherit = "res.partner"

    qbo_customer_id = fields.Char("QBO Customer Id", copy=False, help="QuickBooks database recordset id")
    qbo_vendor_id = fields.Char("QBO Vendor Id", copy=False, help="QuickBooks database recordset id")
    x_quickbooks_exported = fields.Boolean("Exported to Quickbooks ? ", default=False)
    x_quickbooks_updated = fields.Boolean("Updated in Quickbook ?", default=False)

    @api.model
    def _prepare_partner_dict(self, partner, is_customer=False, is_vendor=False):
        vals = {
            'company_type': 'person' if partner.get('Job') else 'company',
            'name': partner.get('DisplayName'),
            'qbo_customer_id': partner.get('Id') if is_customer else '',
            'qbo_vendor_id': partner.get('Id') if is_vendor else '',
            'customer': is_customer,
            'supplier': is_vendor,
            'email': partner.get('PrimaryEmailAddr').get('Address') if partner.get('PrimaryEmailAddr') else '',
            'phone': partner.get('PrimaryPhone').get('FreeFormNumber') if partner.get('PrimaryPhone') else '',
            'mobile': partner.get('Mobile').get('FreeFormNumber') if partner.get('Mobile') else '',
            'website': partner.get('WebAddr').get('URI') if partner.get('WebAddr') else '',
            'active': partner.get('Active'),
            'comment': partner.get('Notes'),

        }

#         child_ids = []
        if 'BillAddr' in partner and partner.get('BillAddr'):
            address_vals = {
                'street': partner.get('BillAddr').get('Line1'),
                'city': partner.get('BillAddr').get('city'),
                'zip': partner.get('BillAddr').get('zip'),
                'state_id': self.env['res.country.state'].get_state_ref(partner.get('BillAddr').get('CountrySubDivisionCode'), partner.get('BillAddr').get('Country')) if partner.get('BillAddr').get('CountrySubDivisionCode') else False,
                'country_id': self.env['res.country'].get_country_ref(partner.get('BillAddr').get('Country')) if partner.get('BillAddr').get('Country') else False,
            }
            vals.update(address_vals)

        if 'ParentRef' in partner:
            if is_customer:
                vals.update({'parent_id': self.get_parent_customer_ref(partner.get('ParentRef').get('value'))})
            if is_vendor:
                vals.update({'parent_id': self.get_parent_vendor_ref(partner.get('ParentRef').get('value'))})

        return vals

    @api.model
    def get_parent_customer_ref(self, qbo_parent_id):
        company = self.env['res.users'].search([('id', '=', self.env.uid)], limit=1).company_id
        partner = self.search([('qbo_customer_id', '=', qbo_parent_id)], limit=1)
        if not partner:
            url_str = company.get_import_query_url()
            url = url_str.get('url') + '/customer/' + qbo_parent_id
            data = requests.request('GET', url, headers=url_str.get('headers'))
            if data:
                partner = self.create_partner(data, is_customer=True)
        return partner.id

    @api.model
    def get_qbo_partner_ref(self, partner):
        if partner.customer:
            if partner.qbo_customer_id or (partner.parent_id and partner.parent_id.qbo_customer_id):
                return partner.qbo_customer_id or partner.parent_id.qbo_customer_id
            else:
                raise ValidationError(_("Partner is not exported to QBO"))
        else:
            if partner.qbo_vendor_id or (partner.parent_id and partner.parent_id.qbo_vendor_id):
                return partner.qbo_vendor_id or partner.parent_id.qbo_vendor_id
            else:
                raise ValidationError(_("Partner is not exported to QBO"))

    @api.model
    def get_parent_vendor_ref(self, qbo_parent_id):
        company = self.env['res.users'].search([('id', '=', self.env.uid)], limit=1).company_id
        partner = self.search([('qbo_vendor_id', '=', qbo_parent_id)], limit=1)
        if not partner:
            url_str = company.get_import_query_url()
            url = url_str.get('url') + '/vendor/' + qbo_parent_id
            data = requests.request('GET', url, headers=url_str.get('headers'))
            if data:
                partner = self.create_partner(data, is_vendor=True)
        return partner.id

    @api.model
    def create_partner(self, data, is_customer=False, is_vendor=False):
        """Create partner object in odoo
        :param data: partner object response return by QBO
        :param is_customer: True if partner is a customer
        :param is_vendor: True if partener is a supplier/vendor
        :return int: last import QBO customer or vendor Id
        """
        res = json.loads(str(data.text))
        brw_partner = False
        if is_customer:
            if 'QueryResponse' in res:
                partners = res.get('QueryResponse').get('Customer', [])
            else:
                partners = [res.get('Customer')] or []
        elif is_vendor:
            if 'QueryResponse' in res:
                partners = res.get('QueryResponse').get('Vendor', [])
            else:
                partners = [res.get('Vendor')] or []
        else:
            partners = []

        for partner in partners:
            vals = self._prepare_partner_dict(partner, is_customer=is_customer, is_vendor=is_vendor)
            brw_partner = self.search([('qbo_customer_id', '=', partner.get('Id'))], limit=1)
            if not brw_partner:
                brw_partner = self.create(vals)
            else:
                brw_partner.write(vals)

#             child_ids = []
            if 'BillAddr' in partner and partner.get('BillAddr'):
                address_vals = {
                    'street': partner.get('BillAddr').get('Line1'),
                    'city': partner.get('BillAddr').get('city'),
                    'zip': partner.get('BillAddr').get('zip'),
                    'state_id': self.env['res.country.state'].get_state_ref(partner.get('BillAddr').get('CountrySubDivisionCode'), partner.get('BillAddr').get('Country')) if partner.get('BillAddr').get('CountrySubDivisionCode') else False,
                    'country_id': self.env['res.country'].get_country_ref(partner.get('BillAddr').get('Country')) if partner.get('BillAddr').get('Country') else False,
                    'type': 'invoice',
                    'parent_id': brw_partner.id
                }
                # Create partner billing address
                bill_addr = self.create(address_vals)

            if 'ShipAddr' in partner and partner.get('ShipAddr'):
                address_vals = {
                    'street': partner.get('ShipAddr').get('Line1'),
                    'city': partner.get('ShipAddr').get('city'),
                    'zip': partner.get('ShipAddr').get('zip'),
                    'state_id': self.env['res.country.state'].get_state_ref(partner.get('ShipAddr').get('CountrySubDivisionCode'), partner.get('ShipAddr').get('Country')) if partner.get('ShipAddr').get('CountrySubDivisionCode') else False,
                    'country_id': self.env['res.country'].get_country_ref(partner.get('ShipAddr').get('Country')) if partner.get('ShipAddr').get('Country') else False,
                    'type': 'delivery',
                    'parent_id': brw_partner.id
                }
                # Create partner billing address
                ship_addr = self.create(address_vals)

            _logger.info(_("Partner created sucessfully! Partner Id: %s" % (brw_partner.id)))
        return brw_partner

ResPartner()


class Respartnercustomization(models.Model):
    _inherit = "res.partner"

    x_quickbooks_exported = fields.Boolean("Exported to Quickbooks ? ", copy=False, default=False)
    x_quickbooks_updated = fields.Boolean("Updated in Quickbook ?", copy=False, default=False)

    ''' For Update Version '''

    def updateExistingCustomer(self):
        ''' Check first if qbo_customer_id exists in quickbooks or not'''
        if self.x_quickbooks_exported or self.qbo_customer_id:
            ''' Hit request ot quickbooks and check response '''
            company = self.env['res.users'].search([('id', '=', self.env.uid)], limit=1).company_id

            ''' GET ACCESS TOKEN '''

            access_token = None
            realmId = None
            if company.access_token:
                access_token = company.access_token
            if company.id:
                realmId = company.realm_id

            if access_token:
                headers = {}
                headers['Authorization'] = 'Bearer ' + str(access_token)
                headers['Content-Type'] = 'application/json'
                headers['Accept'] = 'application/json'

                sql_query = "select Id,SyncToken from customer Where Id = '{}'".format(str(self.qbo_customer_id))

                result = requests.request('GET', company.url + str(realmId) + "/query?query=" + sql_query, headers=headers)
                if result.status_code == 200:
                    parsed_result = result.json()

                    if parsed_result.get('QueryResponse') and parsed_result.get('QueryResponse').get('Customer'):
                        customer_id_retrieved = parsed_result.get('QueryResponse').get('Customer')[0].get('Id')
                        if customer_id_retrieved:
                            ''' HIT UPDATE REQUEST '''
                            syncToken = parsed_result.get('QueryResponse').get('Customer')[0].get('SyncToken')
                            result = self.prepareDictStructure(is_update=True, customer_id_retrieved=customer_id_retrieved, sync_token=syncToken)
                            if result:
                                return result
                            else:
                                return False
                else:
                    return False

    def sendDataToQuickbooksForUpdate(self, dict):

        company = self.env['res.users'].search([('id', '=', self.env.uid)], limit=1).company_id

        ''' GET ACCESS TOKEN '''

        access_token = None
        realmId = None
        parsed_dict = json.dumps(dict)
        if company.access_token:
            access_token = company.access_token
        if company.realm_id:
            realmId = company.realm_id

        if access_token:
            headers = {}
            headers['Authorization'] = 'Bearer ' + str(access_token)
            headers['Content-Type'] = 'application/json'
            headers['Accept'] = 'application/json'

            result = requests.request('POST', company.url + str(realmId) + "/customer?operation=update", headers=headers, data=parsed_dict)
            if result.status_code == 200:
                parsed_result = result.json()
                if parsed_result.get('Customer').get('Id'):
                    self.x_quickbooks_updated = True
                    return parsed_result.get('Customer').get('Id')
                else:
                    return False
            else:
                raise UserError("Error Occured While Updating" + result.text)
                return False

    def prepareDictStructure(self, obj=False, record_type=False, customer_id_retrieved=False, is_update=False, sync_token=False):
        data_object = None

        if obj:
            data_object = obj
        else:
            data_object = self

        ''' This Function Exports Record to Quickbooks '''
        dict = {}
        dict_phone = {}
        dict_email = {}
        dict_mobile = {}
        dict_billAddr = {}
        dict_shipAddr = {}
        dict_parent_ref = {}
        dict_job = {}

        if data_object.mobile:
            dict['Mobile'] = {'FreeFormNumber': str(data_object.mobile)}

        if data_object.website:
            dict['WebAddr'] = {'URI': str(data_object.website)}

        if data_object.comment:
            dict["Notes"] = data_object.comment
#
        if data_object.name:
            dict["GivenName"] = str(data_object.name)
            dict['DisplayName'] = str(data_object.display_name)

        if data_object.title:
            dict["Title"] = data_object.title.name

        if data_object.email:
            dict_email["PrimaryEmailAddr"] = {'Address': str(data_object.email)}

        if data_object.phone:
            dict_phone["PrimaryPhone"] = {'FreeFormNumber': str(data_object.phone)}

        if data_object.type == 'invoice' or data_object.type == 'contact':
            dict_billAddr['BillAddr'] = {'Line1': data_object.street, 'Line2': (data_object.street2 or ""), 'City': (data_object.city or ""),
                                         'Country': data_object.country_id.name, 'CountrySubDivisionCode': data_object.state_id.name,
                                         'PostalCode': data_object.zip}

        if self.type == 'delivery':
            dict_shipAddr['ShipAddr'] = {'Line1': data_object.street, 'Line2': data_object.street2, 'City': data_object.city,
                                         'Country': data_object.country_id.name, 'CountrySubDivisionCode': data_object.state_id.name,
                                         'PostalCode': data_object.zip}

        dict.update(dict_email)
        dict.update(dict_phone)
        dict.update(dict_billAddr)
        dict.update(dict_shipAddr)

        if customer_id_retrieved and record_type and record_type == "indv_company":
            dict_parent_ref['ParentRef'] = {'value': str(customer_id_retrieved)}
            dict.update(dict_parent_ref)

            dict['Job'] = 'true'

        if is_update and customer_id_retrieved:

            dict['Id'] = str(customer_id_retrieved)
            dict['sparse'] = "true"

            ''' Check SyncToken '''
            if sync_token:
                dict['SyncToken'] = str(sync_token)
            result = self.sendDataToQuickbooksForUpdate(dict)
        else:
            result = self.sendDataToQuickbook(dict)

        if result:
            if is_update:
                print (" UPDATED !!!!!!!!!!!!!!")
            else:
                print ("EXPORTED !!!!!!!!!")
            return result
        else:
            print ("ERROR WHILE UPLOADING")
            return False

    def createParentInQuickbooks(self, odoo_partner_object, company):
        ''' This Function Creates a new record in quicbooks and returns its Id
        For attaching with the record of customer which will be created in exportPartner Function'''

        if odoo_partner_object and company:

            result = self.prepareDictStructure(odoo_partner_object, record_type="company")
            if result:
                return result
        else:
            return False

        '''STEP 1 : Retrieve All Data from odoo_partner_object to form a dictionary which will be passed
        to Quickbooks'''

    def checkPartnerInQuickbooks(self, odoo_partner_object):
        ''' Check This Name in Quickbooks '''
        customer_id_retrieved = None
        company = self.env['res.users'].search([('id', '=', self.env.uid)], limit=1).company_id

        if company:

            access_token = None
            realmId = None
            if company.access_token:
                access_token = company.access_token
            if company.realm_id:
                realmId = company.realm_id

            if access_token and realmId:
                ''' Hit Quickbooks and Check Availability '''
                headers = {}
                headers['Authorization'] = 'Bearer ' + str(access_token)
                headers['Content-Type'] = 'application/json'
                headers['Accept'] = 'application/json'

                sql_query = "select Id from customer Where DisplayName = '{}'".format(str(odoo_partner_object.name))
#                 print ("SQL QUERY IS ",sql_query)

                result = requests.request('GET', company.url + str(realmId) + "/query?query=" + sql_query, headers=headers)
                if result.status_code == 200:
                    parsed_result = result.json()

                    if parsed_result.get('QueryResponse') and parsed_result.get('QueryResponse').get('Customer'):
                        customer_id_retrieved = parsed_result.get('QueryResponse').get('Customer')[0].get('Id')
                        if customer_id_retrieved:
                            return customer_id_retrieved
                    if not parsed_result.get('QueryResponse').get('Customer'):
                        new_quickbooks_parent_id = self.createParentInQuickbooks(odoo_partner_object, company)
                        if new_quickbooks_parent_id:
                            odoo_partner_object.x_quickbooks_exported = True
                            odoo_partner_object.qbo_customer_id = new_quickbooks_parent_id
                            return new_quickbooks_parent_id
                        else:
                            print ("Inside Else of new_quickbooks_parent_id")
                        return False

#                     if customer_id_retrieved:
# #                         print ("CUSTOMER ID RETRIEVED IS :", customer_id_retrieved)
#                         return customer_id_retrieved
#                     else:
#                         ''' Create That Parents Record In Quickbooks and Return Its ID '''
#                         new_quickbooks_parent_id = self.createParentInQuickbooks(odoo_partner_object,company)
#                         return False
                else:
                    raise UserError("Error Occured In Partner Search Request" + result.text)
                return False
        else:
            print ("Didnt Got QUickbooks Config")

    def sendDataToQuickbook(self, dict):

        company = self.env['res.users'].search([('id', '=', self._uid)], limit=1).company_id

        ''' GET ACCESS TOKEN '''

        access_token = None
        realmId = None
        parsed_dict = json.dumps(dict)
        if company.access_token:
            access_token = company.access_token
        if company.realm_id:
            realmId = company.realm_id

        if access_token:
            headers = {}
            headers['Authorization'] = 'Bearer ' + str(access_token)
            headers['Content-Type'] = 'application/json'
            headers['Accept'] = 'application/json'

            result = requests.request('POST', company.url + str(realmId) + "/customer", headers=headers, data=parsed_dict)
            if result.status_code == 200:
                parsed_result = result.json()
                if parsed_result.get('Customer').get('Id'):
                    if self.parent_id:
                        self.parent_id.x_quickbooks_exported = True
                    if not self.parent_id:
                        self.x_quickbooks_exported = True
                    return parsed_result.get('Customer').get('Id')
                else:
                    return False
            else:
                raise UserError("Error Occured While Exporting" + result.text)
                return False

    @api.model
    def exportPartner(self):

        if len(self) > 1:
            raise UserError("Select 1 record at a time.")
            return

        if self.x_quickbooks_exported or self.qbo_customer_id:
            '''  If Customer Already Exported to quickbooks then hit update request '''

            # STEP 1 : GET ID FROM QUICKBOOKS USING GET REQUEST QUERY TO QUICKBOOKS
            result = self.updateExistingCustomer()
            if result:
                raise UserError("Update was successful !")
            else:
                raise UserError("Update unsuccessful :(")
        else:

            #             raise UserError("Customer Already Exported To Quickbooks")
            #             return False
            ''' Checking if parent_id is assigned or not if not then first read that parent_id and check in 
            Quickbooks if present if present then make sub customer else first create that company in Quickbooks and 
            attach its reference.
            '''

            if self.parent_id:
                ''' Check self.parent_id.name in Quickbooks '''
                customer_id_retrieved = self.checkPartnerInQuickbooks(self.parent_id)
                if customer_id_retrieved:
                    result = self.prepareDictStructure(record_type="indv_company", customer_id_retrieved=customer_id_retrieved)
                    if result:
                        self.qbo_customer_id = result
                        self.x_quickbooks_exported = True
                else:
                    print ("Customer ID was not retrieved")

            if not self.parent_id:
                result = self.prepareDictStructure(record_type="individual")
                if result:
                    self.qbo_customer_id = result
                    self.x_quickbooks_exported = True

#



