# -*- coding: utf-8 -*-
{
    'name': 'Panther Express Shipping',
    'version': '17.0.1.0.0',
    'category': 'Inventory/Delivery',
    'summary': 'Panther Express shipping integration: shipments, tracking and status webhook',
    'description': """
Panther Express Shipping
========================

Connects Odoo eCommerce / Sales / Inventory with the **Panther Express** shipping API.

Features
--------
* Panther Express delivery carrier (selectable on the eCommerce checkout)
* "Create Panther Shipment" button on the Sales Order and on the Delivery Order
* API client for ``addBulkShipments`` and ``getCurrentStatus``
* Waybill stored on the shipment, on the Sales Order and on the Delivery Order
* Tracking screen (Waybill / Customer / Status)
* Public status webhook: ``/panther/webhook/status``
* Configuration stored in ``ir.config_parameter``
""",
    'author': 'Panther Express',
    'maintainer': 'Panther Express',
    'support': 'support@panther-express.top',
    'website': 'https://panther-express.top',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'sale_management',
        'stock',
        'delivery',
        # Odoo 17 moved the picking side of the carriers (carrier_tracking_ref,
        # "Send to Shipper", the choose.delivery.carrier wizard) to stock_delivery.
        'stock_delivery',
        'website_sale',
    ],
    'data': [
        'security/panther_security.xml',
        'security/ir.model.access.csv',
        'data/panther_sequence_data.xml',
        'data/panther_status_data.xml',
        'data/panther_delivery_data.xml',
        'views/panther_shipment_views.xml',
        'views/panther_status_views.xml',
        'views/res_config_settings_views.xml',
        'views/delivery_carrier_views.xml',
        'views/sale_order_views.xml',
        'views/stock_picking_views.xml',
        'views/res_partner_views.xml',
        'views/panther_track_templates.xml',
        'views/panther_menus.xml',
    ],
    'images': ['static/description/banner.png'],
    'application': True,
    'installable': True,
    'auto_install': False,
}
