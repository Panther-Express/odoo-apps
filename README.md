# Panther Express — Odoo Apps

Official Odoo modules published by **Panther Express**.

One folder per module, at the root of the repository, as required by the
[Odoo Apps store](https://apps.odoo.com/apps).

| Module | Series | Description |
|---|---|---|
| [`panther_express_shipping`](panther_express_shipping/) | 17.0 | Panther Express shipping integration — shipments, waybills, tracking and status webhook |

## Branches

Each branch matches an Odoo series exactly, and the modules on it are written
for that series only:

| Branch | Odoo |
|---|---|
| `17.0` | Odoo 17.0 |

## Installing

Copy the module folder into a directory listed in your `addons_path`, restart
Odoo, then **Apps → Update Apps List → Install**.

```bash
git clone -b 17.0 https://github.com/panther-express/odoo-apps.git
cp -r odoo-apps/panther_express_shipping /opt/odoo/custom-addons/
sudo systemctl restart odoo
```

On **Odoo.sh**, add this repository as a submodule of your project instead.
**Odoo Online (SaaS)** does not accept third-party modules.

## Support

- support@panther-express.top
- https://panther-express.top

## License

LGPL-3. See [`panther_express_shipping/LICENSE`](panther_express_shipping/LICENSE).
