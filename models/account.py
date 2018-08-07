# -*- coding: utf-8 -*-
import json
import logging

import requests

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class AccountAccount(models.Model):
    _inherit = "account.account"

    qbo_id = fields.Char("QBO Id", copy=False, help="QuickBooks database recordset id")
    qbo_acc_type = fields.Many2one('qbo.account.type', string="QBO Type", help="QuickBooks account type")
    qbo_acc_subtype = fields.Many2one('qbo.account.subtype', string="QBO Subtype", help="QuickBooks account subtype")

    @api.onchange('qbo_acc_type')
    def onchange_qbo_acc_type(self):
        self.qbo_acc_subtype = False
        return {'domain': {'qbo_acc_subtype': [('qbo_type_id', '=', self.qbo_acc_type.id)]}}

    @api.model
    def get_account_ref(self, qbo_account_id):
        company = self.env['res.users'].search([('id', '=', self.env.uid)], limit=1).company_id
        account = self.search([('qbo_id', '=', qbo_account_id)], limit=1)
        # If account is not created in odoo then import from QBO and create.
        if not account:
            url_str = company.get_import_query_url()
            url = url_str.get('url') + '/account/' + qbo_account_id
            data = requests.request('GET', url, headers=url_str.get('headers'))
            if data:
                account = self.create_account_account(data)
        return account.id

    @api.model
    def create_account_account(self, data):
        """Create account object in odoo
        :param data: account object response return by QBO
        :return int: last import QBO account Id
        """
        res = json.loads(str(data.text))
        acc_type = self.env['account.account.type']
        qbo_acc_type = self.env['qbo.account.type']
        qbo_acc_subtype = self.env['qbo.account.subtype']
        acc = False
        if 'QueryResponse' in res:
            Account = res.get('QueryResponse').get('Account', [])
        else:
            Account = [res.get('Account')] or []
        for account in Account:
            # Check for account number in QBO account sync data because it is mapped with code in odoo and which is mandatory field.
            if not 'AcctNum' in account:
                raise ValidationError(_("""
                Enable accounts numbers/assign your account numbers to your Chart of Accounts in QBO.
                Follow below steps:
                
                First, turn on the Setting for using account numbers.

                    1. Choose  the Gear icon > Company Settings
                    2. Choose Advanced from the menu on the left.
                    3. In the Chart of Accounts section, click on the Edit icon.
                    4. Place a check mark in the box Enable accounts numbers, and Use account numbers.
                        Click Save and Done.
                
                Next, assign your account numbers.
                
                    1. Choose the Gear icon > Chart of Accounts.
                    2. Click on the Edit icon on the uppser right hand side.
                    3. Enter your Account Numbers in blank box (Account numbers can be up to 7-digits long).
                    4. Click the Save button (Upper right) when you're done with entering your account numbers.
                """))

            if account.get('AccountType') == 'Bank':
                brw_acc_type = acc_type.search([('name', '=', 'Bank and Cash')], limit=1)
            elif account.get('AccountType') == 'Other Current Asset':
                brw_acc_type = acc_type.search([('name', '=', 'Non-current Assets')], limit=1)
            elif account.get('AccountType') == 'Fixed Asset':
                brw_acc_type = acc_type.search([('name', '=', 'Fixed Assets')], limit=1)
            elif account.get('AccountType') == 'Other Asset':
                brw_acc_type = acc_type.search([('name', '=', 'Non-current Assets')], limit=1)
            elif account.get('AccountType') == 'Accounts Receivable':
                brw_acc_type = acc_type.search([('name', '=', 'Receivable')], limit=1)
            elif account.get('AccountType') == 'Equity':
                brw_acc_type = acc_type.search([('name', '=', 'Equity')], limit=1)
            elif account.get('AccountType') == 'Expense':
                brw_acc_type = acc_type.search([('name', '=', 'Expenses')], limit=1)
            elif account.get('AccountType') == 'Other Expense':
                brw_acc_type = acc_type.search([('name', '=', 'Expenses')], limit=1)
            elif account.get('AccountType') == 'Cost Of Goods Sold':
                brw_acc_type = acc_type.search([('name', '=', 'Cost of Revenue')], limit=1)
            elif account.get('AccountType') == 'Accounts Payable':
                brw_acc_type = acc_type.search([('name', '=', 'Payable')], limit=1)
            elif account.get('AccountType') == 'Credit Card':
                brw_acc_type = acc_type.search([('name', '=', 'Credit Card')], limit=1)
            elif account.get('AccountType') == 'Long Term Liability':
                brw_acc_type = acc_type.search([('name', '=', 'Non-current Liabilities')], limit=1)
            elif account.get('AccountType') == 'Other Current Liability':
                brw_acc_type = acc_type.search([('name', '=', 'Current Liabilities')], limit=1)
            elif account.get('AccountType') == 'Income':
                brw_acc_type = acc_type.search([('name', '=', 'Income')], limit=1)
            elif account.get('AccountType') == 'Other Income':
                brw_acc_type = acc_type.search([('name', '=', 'Other Income')], limit=1)

            brw_qbo_acc_type = qbo_acc_type.search([('name', '=', account.get('AccountType'))], limit=1)
            brw_qbo_acc_subtype = qbo_acc_subtype.search([('internal_name', '=', account.get('AccountSubType'))], limit=1)

            vals = {
                'qbo_id': int(account.get('Id')),
                'name': account.get('Name', ''),
                'code': account.get('AcctNum', ''),
                'user_type_id': brw_acc_type.id if brw_acc_type else False,
                'qbo_acc_type': brw_qbo_acc_type.id if brw_qbo_acc_type else False,
                'qbo_acc_subtype': brw_qbo_acc_subtype.id if brw_qbo_acc_subtype else False,
                'reconcile': True if brw_acc_type.name == 'Receivable' or brw_acc_type.name == 'Payable' else False,
            }
            acc = self.env['account.account'].search(['|', ('code', '=', account.get('AcctNum', '')), ('qbo_id', '=', int(account.get('Id')))],
                                                     limit=1)
            #             acc = self.env['account.account'].search([('qbo_id','=',int(account.get('Id')))],limit=1)
            if not acc:
                acc = self.env['account.account'].create(vals)
            else:
                acc.qbo_acc_subtype = False
                acc.write(vals)

            _logger.info(_("Account created sucessfully! Account Id: %s" % (acc.id)))
        return acc

    @api.model
    def export_to_qbo(self):
        """export account to QBO"""
        if self._context.get('active_ids'):
            accounts = self.env['account.account'].browse(self._context.get('active_ids'))
        else:
            accounts = self

        for account in accounts:
            vals = {
                'Name': account.name,
                'AcctNum': account.code,
            }
            if account.qbo_acc_type:
                if account.qbo_acc_type.name == 'Other Expense':
                    acc_type = 'OtherExpense'
                elif account.qbo_acc_type.name == 'Cost Of Goods Sold':
                    acc_type = 'CostOfGoodsSold'
                elif account.qbo_acc_type.name == 'CreditCard':
                    acc_type = 'CreditCard'
                elif account.qbo_acc_type.name == 'Long Term Liability':
                    acc_type = 'LongTermLiability'
                elif account.qbo_acc_type.name == 'Other Current Liability':
                    acc_type = 'OtherCurrentLiability'
                elif account.qbo_acc_type.name == 'Other Income':
                    acc_type = 'OtherIncome'
                else:
                    acc_type = account.qbo_acc_type.name

                vals.update({'AccountType': acc_type})
            elif not account.qbo_acc_subtype:
                raise ValidationError(_("QBO type is required"))
            if account.qbo_acc_subtype:
                vals.update({'AccountSubType': account.qbo_acc_subtype.internal_name})
            elif not account.qbo_acc_type:
                raise ValidationError(_("QBO subtype is required"))
            account.send_account_to_qbo(vals)

    def send_account_to_qbo(self, vals):
        parsed_dict = json.dumps(vals)
        quickbook_config = self.env['res.users'].search([('id', '=', self._uid)], limit=1).company_id
        if quickbook_config.access_token:
            access_token = quickbook_config.access_token
        if quickbook_config.realm_id:
            realmId = quickbook_config.realm_id

        if access_token:
            headers = {}
            headers['Authorization'] = 'Bearer ' + str(access_token)
            headers['Content-Type'] = 'application/json'

            result = requests.request('POST', quickbook_config.url + str(realmId) + "/account", headers=headers, data=parsed_dict)
            if result.status_code == 200:
                response = quickbook_config.convert_xmltodict(result.text)
                # update agency id and last sync id
                self.qbo_id = response.get('IntuitResponse').get('Account').get('Id')
                quickbook_config.last_acc_imported_id = response.get('IntuitResponse').get('Account').get('Id')
                _logger.info(_("%s exported successfully to QBO" % (self.name)))
                return True
            else:
                _logger.error(_("[%s] %s" % (result.status_code, result.reason)))
                raise ValidationError(_("[%s] %s" % (result.status_code, result.reason)))
                return False


AccountAccount()


class QBOAccountType(models.Model):
    _name = 'qbo.account.type'
    _desctiption = 'QBO account type'

    name = fields.Char('Name', required=True, help='')


QBOAccountType()


class QBOAccountSubtype(models.Model):
    _name = 'qbo.account.subtype'
    _description = 'QBO account subtype'

    name = fields.Char('Name', required=True, help='Display name')
    internal_name = fields.Char('Internal use', help="Internally used name")
    qbo_type_id = fields.Many2one('qbo.account.type', string='QBO Type', help="Reference to QBO account type")


QBOAccountSubtype()
