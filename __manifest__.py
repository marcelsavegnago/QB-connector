# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'QuickBooks Online Odoo Connector',
    'category': 'Accounting',
    'description': """
QuickBook Connector
====================

Odoo Quickbooks online connector is used to export invoices/bill from Odoo get them paid in QBO and import paid invoices/bills in Odoo.

This module has following features

    1] Import QBO customer into Odoo
    2] Import QBO supplier from QBO into Odoo
    3] Import QBO account into Odoo
    4] Export account into QBO
    5] Import QBO account tax into Odoo
    6] Export account tax into QBO
    7] Export tax agency into QBO
    8] Import QBO product category into Odoo
    9] Import QBO product into Odoo
    10] Import QBO payment method into Odoo
    11] Import QBO payment term into Odoo
    12] Export customer invoice into QBO
    13] Export supplier bill into QBO
    14] Import QBO customer payment into Odoo
    15] Import QBO supplier bill into Odoo

""",
    'author': 'Pragmatic TechSoft Pvt Ltd.',
    'website': 'http://www.pragtech.co.in',
    'currency': 'EUR',
    'license': 'OPL-1',
    'price': 99.00,
    'version': '11.0.0',
    'depends': ['base', 'sale', 'purchase', 'account'],
    'data': [
        'data/qbo_data.xml',
        'security/ir.model.access.csv',
        'views/res_company_views.xml',
        'views/export_partner.xml',
        'views/account_views.xml',
        'views/product_views.xml',
    ],
    'images': ['static/description/odooquickbook_v11.jpg'],
    'qweb': [],
    'installable': True,
    'auto_install': False,
}
