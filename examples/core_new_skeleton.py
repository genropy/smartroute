"""
Example showing how to use SmartRoute with hierarchical routers and plugins.
"""

from __future__ import annotations

from smartroute import RoutedClass, Router, route


class UsersAPI(RoutedClass):
    routes = Router()

    def __init__(self, label: str):
        self.label = label

    @route("routes")
    def list_users(self):
        return f"user:{self.label}:list"


class ProductsAPI(RoutedClass):
    routes = Router(prefix="prod_")
    admin_routes = Router(prefix="admin_", name="product_admin")

    def __init__(self, label: str):
        self.label = label

    @route("routes")
    def list_products(self):
        return f"product:{self.label}"

    @route("routes")
    def prod_stats(self):
        return f"stats:{self.label}"

    @route("admin_routes")
    def admin_reset(self):
        return f"admin-reset:{self.label}"


class ReportingAPI(RoutedClass):
    reports = Router(name="reports").plug("logging")

    def __init__(self, label: str):
        self.label = label

    @route("reports")
    def daily_report(self):
        return f"report:{self.label}"


class RootAPI(RoutedClass):
    routes = Router(name="root")
    admin_routes = Router(prefix="do_")

    def __init__(self):
        self.users = UsersAPI("alpha")
        self.products = ProductsAPI("beta")
        self.routes.add_child(self.users, name="users")
        self.routes.add_child(self.products, name="products")

    @route("admin_routes")
    def do_healthcheck(self):
        return "OK"
