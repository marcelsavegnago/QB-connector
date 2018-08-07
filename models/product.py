# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime, date

import requests

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ProductCategory(models.Model):
    _inherit = 'product.category'

    qbo_product_category_id = fields.Char("QBO Category Id", copy=False, help="QuickBooks database recordset id")

    @api.model
    def get_category_ref(self, qbo_categ_id):
        company = self.env['res.users'].search([('id', '=', self.env.uid)], limit=1).company_id
        categ = self.search([('qbo_product_category_id', '=', qbo_categ_id)], limit=1)
        # If account is not created in odoo then import from QBO and create.
        if not categ:
            url_str = company.get_import_query_url()
            url = url_str.get('url') + '/item/' + qbo_categ_id + '?minorversion=' + url_str.get('minorversion')
            data = requests.request('GET', url, headers=url_str.get('headers'))
            if data:
                categ = self.create_product_category(data)
        if categ.id:
            return categ.id
        else:
            return False

    @api.model
    def create_product_category(self, data, parent=False):
        """Create product category object in odoo
        :param data: product category object response return by QBO
        :return product.category: product category object
        """
        company = self.env['res.users'].search([('id', '=', self.env.uid)], limit=1).company_id
        res = json.loads(str(data.text))
        categ_obj = False
        if 'QueryResponse' in res:
            categories = res.get('QueryResponse').get('Item', [])
        else:
            categories = [res.get('Item')] or []
        for category in categories:
            if 'ParentRef' in category:
                categ_id = self.create_category_recursively(category)
                categ_obj = self.browse(categ_id)
            else:
                # check if not category present then create otherwise use the same
                vals = {
                    'name': category.get("Name", ''),
                    'qbo_product_category_id': category.get("Id"),
                }
                # If Income or expense account present then map them with odoo Income or expense account
                if 'IncomeAccountRef' in category:
                    account_id = self.get_income_account_ref(category)
                    vals.update({'property_account_income_categ_id': account_id})
                if 'ExpenseAccountRef' in category:
                    account_id = self.get_income_account_ref(category)
                    vals.update({'property_account_expense_categ_id': account_id})

                categ_obj = self.search([('qbo_product_category_id', '=', category.get("Id"))])
                if not categ_obj:
                    categ_obj = self.create(vals)
                else:
                    categ_obj.write(vals)

                self.env.cr.commit()

            _logger.info(_("Product category created sucessfully! Category Id: %s" % (categ_obj.id)))
        return categ_obj

    @api.model
    def create_category_recursively(self, category):
        if not 'ParentRef' in category:
            # Create parent category
            # check if not category present then create otherwise use the same
            vals = {
                'name': category.get("Name", ''),
                'qbo_product_category_id': category.get("Id"),
            }
            # If Income or expense account present then map them with odoo Income or expense account
            if 'IncomeAccountRef' in category:
                account_id = self.get_income_account_ref(category)
                vals.update({'property_account_income_categ_id': account_id})
            if 'ExpenseAccountRef' in category:
                account_id = self.get_income_account_ref(category)
                vals.update({'property_account_expense_categ_id': account_id})

            categ_obj = self.search([('qbo_product_category_id', '=', category.get("Id"))])
            if not categ_obj:
                categ_obj = self.create(vals)
            else:
                categ_obj.write(vals)

            self.env.cr.commit()
            return categ_obj.id
        else:
            # read category object from QBO
            company = self.env['res.users'].search([('id', '=', self.env.uid)], limit=1).company_id
            url_str = company.get_import_query_url()
            url = url_str.get('url') + '/item/%s' % category.get('ParentRef').get('value')
            data = requests.request('GET', url, headers=url_str.get('headers'))
            parent_category = json.loads(str(data.text))
            self.env.cr.commit()
            # Create sub category
            # check if not category present then create otherwise use the same
            #             categ_obj = self.search([('qbo_product_category_id','=',category.get("Id"))])
            #             vals = {
            #                 'name': category.get('Name'),
            #                 'qbo_product_category_id': category.get("Id")
            #             }
            # If Income or expense account present then map them with odoo Income or expense account
            income_account_id = False
            expense_account_id = False
            if 'IncomeAccountRef' in category:
                income_account_id = self.self.env['account.account'].get_account_ref(category.get('IncomeAccountRef').get('value'))
            #                 vals.update({'property_account_income_categ_id': account_id})
            if 'ExpenseAccountRef' in category:
                expense_account_id = self.env['account.account'].get_account_ref(category.get('ExpenseAccountRef').get('value'))
            #                 vals.update({'property_account_expense_categ_id': account_id})
            return self.create({'name': category.get('Name'),
                                'qbo_product_category_id': category.get("Id"),
                                'property_account_income_categ_id': income_account_id,
                                'property_account_expense_categ_id': expense_account_id,
                                'parent_id': self.create_category_recursively(parent_category.get('Item'))}).id


ProductCategory()


class Product(models.Model):
    _inherit = "product.template"

    # related to display product product information if is_product_variant
    qbo_product_id = fields.Char('QBO Product Id', related='product_variant_ids.qbo_product_id', help="")

    x_is_exported = fields.Boolean('is_exported', default=False)

    def get_asset_account_ref(self):
        company = self.env['res.users'].search([('id', '=', self._uid)], limit=1).company_id
        if company.access_token:
            access_token = company.access_token
        if company.realm_id:
            realmId = company.realm_id
        if access_token:
            headers = {}
            headers['Authorization'] = 'Bearer ' + str(access_token)
            headers['Content-Type'] = 'application/json'
            headers['accept'] = 'application/json'
            result = requests.request('GET',
                                      company.url + str(realmId) + "/query?query=select name,acctnum from account where Name like 'Inventory Asset'",
                                      headers=headers)
            if result.status_code == 200:
                resp = json.loads(result.text)
                if resp.get('QueryResponse').get('Account')[0]:
                    data_dict = {
                        'name': resp.get('QueryResponse').get('Account')[0].get('Name'),
                        'value': resp.get('QueryResponse').get('Account')[0].get('Id')
                    }
                    return data_dict
                else:
                    return False
            else:
                return False

    @api.model
    def get_qbo_product_ref(self, product):
        if product.qbo_product_id:
            return product.qbo_product_id
        else:
            raise ValidationError(_("Product not exported to QBO."))

    def getSyncToken(self, item_id):
        company = self.env['res.users'].search([('id', '=', self._uid)], limit=1).company_id

        # Get SyncToken and of Id
        sql_query = "select Id,SyncToken from item Where Id = '{}'".format(str(item_id))

        if company.access_token:
            access_token = company.access_token

        if company.realm_id:
            realmId = company.realm_id

        if access_token:
            headers = {}
            headers['Authorization'] = 'Bearer ' + str(access_token)
            headers['Content-Type'] = 'application/json'
            headers['accept'] = 'application/json'

        result = requests.request('GET', company.url + str(realmId) + "/query?query=" + sql_query, headers=headers)
        if result.status_code == 200:
            parsed_result = result.json()
            if parsed_result.get('QueryResponse') and parsed_result.get('QueryResponse').get('Item'):
                ''' GET SYNC TOKEN'''
                syncToken = parsed_result.get('QueryResponse').get('Item')[0].get('SyncToken')
                return syncToken
            else:
                return False
        else:
            return False

    @api.multi
    def export_product_to_qbo(self):
        for product_id in self:

            ''' Check If expense and income account is set or not '''
            if not product_id.property_account_income_id:
                raise ValidationError('Please Set Income Account for {}'.format(product_id.name))
                return False
            if not product_id.property_account_expense_id:
                raise ValidationError('Please Set Expense Account for {}'.format(product_id.name))
                return False

            company = self.env['res.users'].search([('id', '=', self._uid)], limit=1).company_id
            d = datetime.strptime(str(date.today()), '%Y-%m-%d')
            as_of_today = date.strftime(d, "%d/%m/%y")
            #         Product details to be exported to Quickbooks
            vals = {
                "Name": product_id.name,
                "IncomeAccountRef": {
                    "value": product_id.property_account_income_id.qbo_id

                },
                "ExpenseAccountRef": {
                    "value": product_id.property_account_expense_id.qbo_id
                },

                "UnitPrice": product_id.list_price,

                "InvStartDate": str(date.today())
            }

            if product_id.standard_price:
                vals.update({'PurchaseCost': product_id.standard_price})

            if product_id.description_sale:
                vals.update({
                    'Description': product_id.description_sale
                })

            if product_id.default_code:
                vals.update({'Sku': product_id.default_code})

            if product_id.description_purchase:
                vals.update({'PurchaseDesc': product_id.description_purchase})

            if product_id.type == "consu":
                vals.update({
                    'Type': 'NonInventory'
                })

            if product_id.type == "service":
                vals.update({
                    'Type': 'Service'
                })

            if product_id.type == "product":

                # Get quickbooks id of inventory asset COA from odoo
                inv_asset = self.env['account.account'].search([('name', 'like', 'Inventory Asset')], limit=1)
                vals.update({
                    "QtyOnHand": product_id.qty_available,
                    'Type': 'Inventory',
                    'TrackQtyOnHand': True
                })
                if inv_asset and inv_asset.qbo_id:
                    vals.update({
                        'AssetAccountRef': {
                            'value': inv_asset.qbo_id
                        }
                    })

            if product_id.categ_id.qbo_product_category_id:
                vals.update({
                    'SubItem': True,
                    'ParentRef': {
                        'value': product_id.categ_id.qbo_product_category_id
                    }
                })

            if company.access_token:
                access_token = company.access_token
            if company.realm_id:
                realmId = company.realm_id
            if access_token:
                print('im innnnnnnnnnnnnnnn:::::::::::::::::::;')
                headers = {}
                headers['Authorization'] = 'Bearer ' + str(access_token)
                headers['Content-Type'] = 'application/json'
                headers['accept'] = 'application/json'

                if product_id.qbo_product_id and product_id.x_is_exported:
                    vals.update({'sparse': True})
                    synctoken = self.getSyncToken(product_id.qbo_product_id)

                    if synctoken:
                        print('im sync:::::::::::::::::::;')
                        vals.update({'Id': product_id.qbo_product_id})
                        vals.update({'SyncToken': synctoken})

                        del vals['QtyOnHand']
                        parsed_dict = json.dumps(vals)
                        result = requests.request('POST', company.url + str(realmId) + "/item/?operation=update&minorversion=12", headers=headers,
                                                  data=parsed_dict)

                else:
                    print('In Else part')
                    parsed_dict = json.dumps(vals)
                    result = requests.request('POST', company.url + str(realmId) + "/item?minorversion=12", headers=headers, data=parsed_dict)
                    print('\n\n', parsed_dict, result.text, result.status_code)

                if result.status_code == 200:
                    print('\n\n\n successfully exported')
                    resp_parsed = json.loads(result.text)
                    if resp_parsed.get('Item').get('Id'):
                        ''' Set is_exported to true and add reference of newely created procut in quickbooks'''
                        product_id.x_is_exported = True
                        product_id.qbo_product_id = resp_parsed.get('Item').get('Id')

    @api.model
    def create_product(self, data, parent=False):
        """Create product object in odoo
        :param data: product object response return by QBO
        :return product.template: product template object
        """
        account = self.env['account.account']
        tax = self.env['account.tax']
        category = self.env['product.category']
        prod_obj = False
        res = json.loads(str(data.text))
        if 'QueryResponse' in res:
            products = res.get('QueryResponse').get('Item', [])
        else:
            products = [res.get('Item')] or []

        for product in products:
            if product.get('Type') == 'Service' or product.get('Type') == 'Inventory' or product.get('Type') == 'NonInventory':
                product_type = 'consu'
                if product.get('Type') == 'NonInventory':
                    product_type = 'consu'
                elif product.get('Type') == 'Inventory':
                    product_type = 'product'
                elif product.get('Type') == 'Service':
                    product_type = 'service'

                vals = {
                    'name': product.get('Name', ''),
                    'description_sale': product.get('Description', ''),
                    'description_purchase': product.get('PurchaseDesc', ''),
                    'list_price': product.get('UnitPrice', ''),
                    'standard_price': product.get('PurchaseCost', ''),
                    'default_code': product.get('Sku', ''),
                    'type': product_type,
                    'active': product.get('Active'),
                    'property_account_income_id': account.get_account_ref(
                        product.get('IncomeAccountRef').get('value')) if 'IncomeAccountRef' in product else False,
                    'property_account_expense_id': account.get_account_ref(
                        product.get('ExpenseAccountRef').get('value')) if 'ExpenseAccountRef' in product else False,
                    #                     'taxes_id' : [(6,0,[tax.get_account_tax_ref(product.get('SalesTaxCodeRef').get('value'),product.get('SalesTaxCodeRef').get('name'))])] if 'SalesTaxCodeRef' in product else False,
                    #                     'supplier_taxes_id' : [(6,0,[tax.get_account_tax_ref(product.get('PurchaseTaxCodeRef').get('value'),product.get('PurchaseTaxCodeRef').get('name'))])] if 'PurchaseTaxCodeRef' in product else False,
                    'qbo_product_id': product.get('Id'),
                }
                categ_id = category.get_category_ref(product.get('ParentRef').get('value')) if 'ParentRef' in product else False,

                if categ_id and not False in categ_id:
                    vals.update({
                        'categ_id': categ_id
                    })
                else:
                    _logger.info(_("Categ ID was not found"))

                if 'SalesTaxCodeRef' in product:
                    tax_id = tax.get_account_tax_ref(product.get('SalesTaxCodeRef').get('value'), product.get('SalesTaxCodeRef').get('name'),
                                                     type_tax_use="sale")
                    if tax_id:
                        vals.update({'taxes_id': [6, 0, [tax_id]]})
                if 'PurchaseTaxCodeRef' in product:
                    tax_id = tax.get_account_tax_ref(product.get('PurchaseTaxCodeRef').get('value'), product.get('PurchaseTaxCodeRef').get('name'),
                                                     type_tax_use="purchase")
                    if tax_id:
                        vals.update({'supplier_taxes_id': [6, 0, [tax_id]]})

                if product.get('Sku'):
                    prod_obj = self.search(['|', ('default_code', '=', product.get('Sku')), ('qbo_product_id', '=', product.get("Id"))])
                else:
                    prod_obj = self.search([('qbo_product_id', '=', product.get("Id"))])

                if len(prod_obj) > 1:
                    raise ValidationError(_("Found multiple with internal reference %s, expected singleton" % (str([p.name for p in prod_obj]))))

                if not prod_obj:
                    prod_obj = self.create(vals)
                else:
                    prod_obj.write(vals)

                self.env.cr.commit()

                _logger.info(_("Product created sucessfully! product template Id: %s" % (prod_obj.id)))

        return prod_obj


Product()


class ProductProduct(models.Model):
    _inherit = "product.product"

    qbo_product_id = fields.Char('QBO Product ID', help="Refer to QBO Item Id")


ProductProduct()


class Inventory(models.Model):
    _inherit = "stock.inventory"

    qbo_update = fields.Boolean("QBO Update", default=False)


Inventory()
