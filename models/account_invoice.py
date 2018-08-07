# -*- coding: utf-8 -*-
import json
import logging
import re

import requests

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class AccountInvoice(models.Model):
    _inherit = "account.invoice"

    qbo_invoice_id = fields.Char("QBO Invoice Id", copy=False, help="QBO Invoice Id")

    @api.model
    def _prepare_invoice_export_line_dict(self, line):
        #         line = self
        company = self.env['res.users'].search([('id', '=', self._uid)], limit=1).company_id
        vals = {
            'Description': line.name,
            'Amount': line.price_subtotal,
        }
        if company.country_id.code == 'US':
            if line.invoice_line_tax_ids:
                taxCodeRefValue = 'TAX'
            else:
                taxCodeRefValue = 'NON'
        else:
            taxCodeRefValue = self.env['account.tax'].get_qbo_tax_code(line.invoice_line_tax_ids)

        if self.partner_id.customer:
            vals.update({
                'DetailType': 'SalesItemLineDetail',
                'SalesItemLineDetail': {
                    'ItemRef': {'value': self.env['product.template'].get_qbo_product_ref(line.product_id)},
                    'TaxCodeRef': {'value': taxCodeRefValue},
                    'UnitPrice': line.price_unit,
                    'Qty': line.quantity,
                }
            })
        elif self.partner_id.supplier:
            vals.update({
                'DetailType': 'ItemBasedExpenseLineDetail',
                'ItemBasedExpenseLineDetail': {
                    'ItemRef': {'value': self.env['product.template'].get_qbo_product_ref(line.product_id)},
                    'TaxCodeRef': {'value': taxCodeRefValue},
                    'UnitPrice': line.price_unit,
                    'Qty': line.quantity,
                    #                     'BillableStatus' : 'Billable',
                }
            })
        return vals

    @api.model
    def _prepare_invoice_export_dict(self):
        invoice = self
        vals = {
            'DocNumber': invoice.number,
            'TxnDate': invoice.date_invoice,
            'DueDate': invoice.date_due,
        }
        if invoice.partner_id.customer:
            vals.update({'CustomerRef': {'value': self.env['res.partner'].get_qbo_partner_ref(invoice.partner_id)}})
        elif invoice.partner_id.supplier:
            vals.update({'VendorRef': {'value': self.env['res.partner'].get_qbo_partner_ref(invoice.partner_id)}})

        lst_line = []
        for line in invoice.invoice_line_ids:
            line_vals = self._prepare_invoice_export_line_dict(line)
            lst_line.append(line_vals)
        vals.update({'Line': lst_line})
        return vals

    @api.model
    def export_to_qbo(self):
        """export account invoice to QBO"""
        quickbook_config = self.env['res.users'].search([('id', '=', self._uid)], limit=1).company_id
        if self._context.get('active_ids'):
            invoices = self.browse(self._context.get('active_ids'))
        else:
            invoices = self

        for invoice in invoices:
            if invoice.qbo_invoice_id:
                raise ValidationError(_("%s invoice is already exported to QBO. Please, export a different invoice."))
            if invoice.state == 'open':
                vals = invoice._prepare_invoice_export_dict()
                parsed_dict = json.dumps(vals)
                if quickbook_config.access_token:
                    access_token = quickbook_config.access_token
                if quickbook_config.realm_id:
                    realmId = quickbook_config.realm_id

                if access_token:
                    headers = {}
                    headers['Authorization'] = 'Bearer ' + str(access_token)
                    headers['Content-Type'] = 'application/json'

                    if invoice.partner_id.customer:
                        result = requests.request('POST', quickbook_config.url + str(realmId) + "/invoice", headers=headers, data=parsed_dict)
                    elif invoice.partner_id.supplier:
                        result = requests.request('POST', quickbook_config.url + str(realmId) + "/bill", headers=headers, data=parsed_dict)

                    if result.status_code == 200:
                        response = quickbook_config.convert_xmltodict(result.text)
                        # update QBO invoice id
                        if invoice.partner_id.customer:
                            invoice.qbo_invoice_id = response.get('IntuitResponse').get('Invoice').get('Id')
                        elif invoice.partner_id.supplier:
                            invoice.qbo_invoice_id = response.get('IntuitResponse').get('Bill').get('Id')
                            #                     quickbook_config.last_acc_imported_id = response.get('IntuitResponse').get('Account').get('Id')
                        _logger.info(_("%s exported successfully to QBO" % (invoice.number)))
                    #                         return True
                    else:
                        _logger.error(_("[%s] %s" % (result.status_code, result.reason)))
                        raise ValidationError(_("[%s] %s %s" % (result.status_code, result.reason, result.text)))
                    #                         return False
            else:
                raise ValidationError(_("Only open state invoice is exported to QBO."))


AccountInvoice()


class QBOPaymentMethod(models.Model):
    _name = "qbo.payment.method"
    _description = "QBO payment method"

    qbo_method_id = fields.Char("QBO Payment Method Id", copy=False, help="QuickBooks database recordset id")
    name = fields.Char("Name", required=True, help="Name of the payment method.")
    type = fields.Selection([('CREDIT_CARD', 'Credit Card'), ('NON_CREDIT_CARD', 'Non Credit Card')], string="Type",
                            help="Defines the type of payment. Valid values include CREDIT_CARD or NON_CREDIT_CARD.")
    active = fields.Boolean("Active", default=True)

    @api.model
    def get_payment_method_ref(self, qbo_method_id):
        company = self.env['res.users'].search([('id', '=', self.env.uid)], limit=1).company_id
        method = self.search([('qbo_method_id', '=', qbo_method_id)], limit=1)
        # If account is not created in odoo then import from QBO and create.
        if not method:
            url_str = company.get_import_query_url()
            url = url_str.get('url') + '/paymentmethod/' + qbo_method_id
            data = requests.request('GET', url, headers=url_str.get('headers'))
            if data:
                method = self.create_payment_method(data)
        return method.id

    @api.model
    def create_payment_method(self, data):
        """Import payment method from QBO
        :param data: payment method object response return by QBO
        :return qbo.payment.method: qbo payment method object 
        """
        res = json.loads(str(data.text))
        if 'QueryResponse' in res:
            PaymentMethod = res.get('QueryResponse').get('PaymentMethod', [])
        else:
            PaymentMethod = [res.get('PaymentMethod')] or []
        for method in PaymentMethod:
            vals = {
                'name': method.get("Name", ''),
                'qbo_method_id': method.get("Id"),
                'type': method.get('Type'),
                'active': method.get('Active'),
            }
            method_obj = self.create(vals)
            _logger.info(_("Payment Method created sucessfully! Payment Method Id: %s" % (method_obj.id)))
        return method_obj

    @api.model
    def export_to_qbo(self):
        """Export payment method to QBO"""
        if self._context.get('method_id'):
            payment_methods = self
        else:
            payment_methods = self.browse(self._context.get('active_ids'))

        for method in payment_methods:
            vals = {
                'Name': method.name,
            }
            if method.type:
                vals.update({'Type': method.type})
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

                result = requests.request('POST', quickbook_config.url + str(realmId) + "/paymentmethod", headers=headers, data=parsed_dict)

                if result.status_code == 200:
                    # response text is either xml string or json string
                    data = re.sub(r'\s+', '', result.text)
                    if (re.match(r'^<.+>$', data)):
                        response = quickbook_config.convert_xmltodict(result.text)
                        response = response.get('IntuitResponse')
                    if (re.match(r'^({|[).+(}|])$', data)):
                        response = json.loads(result.text, encoding='utf-8')
                    if response:
                        # update agency id and last sync id
                        method.qbo_method_id = response.get('PaymentMethod').get('Id')
                        quickbook_config.last_imported_tax_agency_id = response.get('PaymentMethod').get('Id')

                    _logger.info(_("%s exported successfully to QBO" % (method.name)))
                else:
                    _logger.error(_("[%s] %s" % (result.status_code, result.reason)))
                    raise ValidationError(_("[%s] %s %s" % (result.status_code, result.reason, result.text)))


QBOPaymentMethod()


class AccountPayment(models.Model):
    _inherit = "account.payment"

    qbo_payment_id = fields.Char("QBO Payment Id", copy=False, help="QuickBooks database recordset id")
    qbo_bill_payment_id = fields.Char("QBO Bill Payment Id", copy=False, help="QuickBooks database recordset id")
    qbo_payment_ref = fields.Char("QBO Payment Ref", help="QBO payment reference")
    qbo_payment_method_id = fields.Many2one('qbo.payment.method', string="QBO Payment Method", help="QBO Payment Method Reference")

    @api.model
    def _prepare_payment_dict(self, payment):
        vals = {
            'amount': payment.get('TotalAmt'),
            'payment_date': payment.get('TxnDate'),
            'qbo_payment_ref': payment.get('PaymentRefNum') if payment.get('PaymentRefNum') else False,
            'payment_method_id': 1,
        }
        if 'CustomerRef' in payment:
            customer_id = self.env['res.partner'].get_parent_customer_ref(payment.get('CustomerRef').get('value'))
            vals.update({
                'partner_type': 'customer',
                'partner_id': customer_id,
                'qbo_payment_id': payment.get("Id"),
            })
        if 'VendorRef' in payment:
            vendor_id = self.env['res.partner'].get_parent_vendor_ref(payment.get('VendorRef').get('value'))
            vals.update({
                'partner_type': 'supplier',
                'partner_id': vendor_id,
                'qbo_bill_payment_id': payment.get("Id"),
            })

        if 'PaymentMethodRef' in payment:
            method_id = self.env['qbo.payment.method'].get_payment_method_ref(payment.get('PaymentMethodRef').get('value'))
            vals.update({'qbo_payment_method_id': method_id})
        # For payment
        if 'DepositToAccountRef' in payment:
            journal_id = self.env['account.journal'].get_journal_from_account(payment.get('DepositToAccountRef').get('value'))
            vals.update({'journal_id': journal_id})

        # For Bill payment
        if 'APAccountRef' in payment:
            journal_id = self.env['account.journal'].get_journal_from_account(payment.get('APAccountRef').get('value'))
            vals.update({'journal_id': journal_id})
        elif 'CheckPayment' in payment:
            journal_id = self.env['account.journal'].get_journal_from_account(payment.get('CheckPayment').get('BankAccountRef').get('value'))
            vals.update({'journal_id': journal_id})
        elif 'CreditCardPayment' in payment:
            journal_id = self.env['account.journal'].get_journal_from_account(payment.get('CreditCardPayment').get('CCAccountRef').get('value'))
            vals.update({'journal_id': journal_id})

        return vals

    @api.model
    def create_payment(self, data, is_customer=False, is_vendor=False):
        """Import payment from QBO
        :param data: payment object response return by QBO
        :return account.payment: account payment object 
        """
        res = json.loads(str(data.text))
        if is_customer:
            if 'QueryResponse' in res:
                Payments = res.get('QueryResponse').get('Payment', [])
            else:
                Payments = [res.get('Payment')] or []
        elif is_vendor:
            if 'QueryResponse' in res:
                Payments = res.get('QueryResponse').get('BillPayment', [])
            else:
                Payments = [res.get('BillPayment')] or []

        payment_obj = False
        for payment in Payments:
            invoice = False
            if payment is None:
                payment = False
            if payment and 'LinkedTxn' in payment.get('Line')[0]:
                txn = payment.get('Line')[0].get('LinkedTxn')
                if txn and (txn[0].get('TxnType') == 'Invoice' or txn[0].get('TxnType') == 'Bill'):
                    qbo_inv_ref = txn[0].get('TxnId')
                    invoice = self.env['account.invoice'].search([('qbo_invoice_id', '=', qbo_inv_ref)], limit=1)
            if not invoice:
                continue
            vals = self._prepare_payment_dict(payment)
            vals.update({'communication': invoice.number})
            if invoice.partner_id.customer:
                vals.update({'payment_type': 'inbound'})
                payment_obj = self.search([('qbo_payment_id', '=', payment.get("Id"))], limit=1)
            elif invoice.partner_id.supplier:
                vals.update({'payment_type': 'outbound'})
                payment_obj = self.search([('qbo_bill_payment_id', '=', payment.get("Id"))], limit=1)

            if not payment_obj:
                if 'journal_id' not in vals:
                    raise ValidationError(_('Payment Journal required'))
                    # create payment
                payment_obj = self.create(vals)
                payment_obj.post()
                # get account move line
            #                 move_ids = self.env['account.move.line'].search([('payment_id','=',payment_obj.id)]).mapped('id')
            #                 #call assign_outstanding_credit() method by passing account move line ids to link invoice with payment
            #                 invoice = self.env['account.invoice'].search([('number','=',vals.get('communication'))],limit=1)
            #                 for move_line_id in move_ids:
            #                     invoice.assign_outstanding_credit(move_line_id)


            #                 invoice.post()
            #                 invoice._get_outstanding_info_JSON()
            #                 payment_obj.post()

            #             else:
            #                 payment_obj.write(vals)

            _logger.info(_("Payment created sucessfully! Payment Id: %s" % (payment_obj.id)))
        return payment_obj


AccountPayment()


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    #     qbo_payment_method_id = fields.Many2one('qbo.payment.method', string='QBO Payment Method', help='QBO payment method reference, used in payment import from QBO.')

    def get_journal_from_account(self, qbo_account_id):
        account_id = self.env['account.account'].get_account_ref(qbo_account_id)
        account = self.env['account.account'].browse(account_id)
        journal_id = self.search([('type', 'in', ['bank', 'cash']), ('default_debit_account_id', '=', account_id)], limit=1)
        if not journal_id:
            raise ValidationError(_("Please, define payment journal for %s account" % (account.name)))
        return journal_id.id


AccountJournal()
