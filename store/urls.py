from django.urls import path
from . import views

app_name = 'store'

urlpatterns = [
    path('', views.index, name='index'),
    path('product/<slug:slug>/', views.product_detail, name='product_detail'),
    path('cart/', views.cart_view, name='cart_view'),
    path('cart/add/<int:product_id>/', views.cart_add, name='cart_add'),
    path('cart/remove/<int:product_id>/', views.cart_remove, name='cart_remove'),
    path('cart/update-ajax/', views.cart_update_ajax, name='cart_update_ajax'),
    path('checkout/', views.checkout, name='checkout'),
    path('shipping-calc/', views.shipping_calc_ajax, name='shipping_calc_ajax'),
    path('order/success/<str:order_number>/', views.order_success, name='order_success'),
    path('track/', views.order_track, name='order_track'),
    path('story-and-faq/', views.about_story, name='about_story'),
    path('sitemap.xml', views.sitemap_xml, name='sitemap_xml'),
    path('robots.txt', views.robots_txt, name='robots_txt'),
    path('404/', views.custom_404_view, name='custom_404'),
    path('500/', views.custom_500_view, name='custom_500'),
    path('api/pathao/webhook/', views.pathao_webhook, name='pathao_webhook'),
]

