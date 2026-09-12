from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.dashboard_index, name='index'),
    path('orders/', views.orders_list, name='orders'),
    path('orders/trash/', views.orders_trash, name='orders_trash'),
    path('orders/create/', views.create_manual_order, name='create_manual_order'),
    path('inventory/', views.stock_manager, name='stock_manager'),
    path('damage-returns/', views.damage_returns_manager, name='damage_returns'),
    path('expenses/', views.expense_manager, name='expenses'),
    path('statement/', views.financial_statement, name='statement'),
    path('statement/print/', views.financial_statement_print, name='statement_print'),
    path('pickle-categories/', views.pickle_categories_manager, name='pickle_categories'),
    path('expense-categories/', views.expense_categories_manager, name='expense_categories'),
    path('admin-users/', views.admin_users_manager, name='admin_users'),
    path('reviews/', views.reviews_manager, name='reviews'),
    path('login/', views.dashboard_login, name='login'),
    path('logout/', views.dashboard_logout, name='logout'),
    path('order/<str:order_number>/', views.order_detail, name='order_detail'),
    path('order/<str:order_number>/delete/', views.delete_order, name='delete_order'),
    path('orders/delete/<str:order_number>/', views.delete_order, name='delete_order_alt'),
    path('order/<str:order_number>/restore/', views.restore_order, name='restore_order'),
    path('order/<str:order_number>/permanent-delete/', views.permanent_delete_order, name='permanent_delete_order'),
    path('order/<str:order_number>/edit-customer/', views.edit_order_customer, name='edit_order_customer'),
    path('order/<str:order_number>/quick-status/', views.update_order_status_quick, name='update_order_status_quick'),
    path('order/<str:order_number>/mark-returned/', views.mark_order_returned, name='mark_order_returned'),
    path('order/<str:order_number>/invoice/', views.order_invoice, name='order_invoice'),
    path('api/order-notifications/', views.order_notifications_api, name='api_order_notifications'),
    path('api/launch-driver/', views.launch_pos_driver, name='api_launch_pos_driver'),
]
