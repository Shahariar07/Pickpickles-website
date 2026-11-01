from django import template
from django.utils.safestring import mark_safe

register = template.Library()

@register.simple_tag
def webpush_header():
    return mark_safe('')

@register.simple_tag
def webpush_button():
    return mark_safe('')
