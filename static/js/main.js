/* =========================================================
   PICKPICKLES - Interactive JavaScript & AJAX Cart Engine
   ========================================================= */

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

function getCsrfToken() {
    const metaTag = document.querySelector('meta[name="csrf-token"]');
    if (metaTag && metaTag.getAttribute('content')) {
        return metaTag.getAttribute('content');
    }
    const inputTag = document.querySelector('input[name=csrfmiddlewaretoken]');
    if (inputTag && inputTag.value) {
        return inputTag.value;
    }
    return getCookie('csrftoken') || '';
}

// Toggle Slide Drawer
function toggleCartDrawer(open) {
    const drawer = document.getElementById('cartDrawer');
    const backdrop = document.getElementById('cartDrawerBackdrop');
    if (!drawer || !backdrop) return;

    if (open) {
        drawer.classList.add('open');
        backdrop.classList.add('open');
        document.body.style.overflow = 'hidden';
    } else {
        drawer.classList.remove('open');
        backdrop.classList.remove('open');
        document.body.style.overflow = '';
    }
}

// Show Floating Toast Notification
function showToast(message) {
    let toast = document.getElementById('toastNotification');
    let msgEl = document.getElementById('toastMessage');
    
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'toastNotification';
        toast.className = 'fixed bottom-24 right-4 z-50 bg-slate-900 text-white px-5 py-3 rounded-2xl shadow-2xl flex items-center gap-3 border border-emerald-500/40 transform transition-all duration-300 translate-y-20 opacity-0';
        toast.innerHTML = '<span class="text-xl">🥒</span><span id="toastMessage" class="text-xs sm:text-sm font-bold"></span>';
        document.body.appendChild(toast);
        msgEl = document.getElementById('toastMessage');
    }

    msgEl.innerText = message;
    toast.classList.remove('translate-y-20', 'opacity-0');
    toast.classList.add('translate-y-0', 'opacity-100', 'show');

    setTimeout(() => {
        toast.classList.remove('translate-y-0', 'opacity-100', 'show');
        toast.classList.add('translate-y-20', 'opacity-0');
    }, 3200);
}

// Unified Free Delivery Progress Updater (Drawer & Cart Page)
function updateFreeDeliveryProgress(totalItems) {
    const count = parseInt(totalItems, 10) || 0;
    const isFreeDelivery = count >= 4;
    const remainingForFree = Math.max(0, 4 - count);
    const progressPercent = isFreeDelivery ? 100 : Math.min(100, Math.round((count / 4) * 100));

    // 1. Drawer Elements
    const freeMsgEl = document.getElementById('drawerFreeDeliveryMsg');
    const freeRemainingEl = document.getElementById('drawerFreeDeliveryRemaining');
    const freePercentEl = document.getElementById('drawerFreeDeliveryPercent');
    const freeBarEl = document.getElementById('drawerFreeDeliveryBar');
    const deliveryNoteEl = document.getElementById('drawerDeliveryNote');

    if (freeMsgEl) {
        if (isFreeDelivery) {
            freeMsgEl.innerHTML = '🎉 <strong>FREE Delivery Unlocked!</strong>';
        } else {
            freeMsgEl.innerHTML = `🚚 Add <strong><span id="drawerFreeDeliveryRemaining">${remainingForFree}</span> more jar${remainingForFree > 1 ? 's' : ''}</strong> for FREE Delivery!`;
        }
    }
    if (freePercentEl) freePercentEl.innerText = `${progressPercent}%`;
    if (freeBarEl) freeBarEl.style.width = `${progressPercent}%`;
    if (deliveryNoteEl) {
        if (isFreeDelivery) {
            deliveryNoteEl.innerHTML = '<span class="text-emerald-700 font-bold">🎉 FREE Nationwide Delivery Applied!</span>';
        } else {
            deliveryNoteEl.innerHTML = '<span class="text-gray-500">Flat ৳150 Nationwide Delivery • <strong>Free on 4+ jars</strong></span>';
        }
    }

    // 2. Cart Page Banner Elements
    const pageFreeBanner = document.getElementById('freeDeliveryBanner');
    const pageFreeIcon = document.getElementById('freeDeliveryIcon');
    const pageFreeText = document.getElementById('freeDeliveryText');
    const pageFreeProgress = document.getElementById('freeDeliveryProgressBar');
    const pageFreeSubtext = document.getElementById('freeDeliverySubtext');

    if (pageFreeBanner) {
        if (isFreeDelivery) {
            pageFreeBanner.className = "p-3.5 rounded-2xl border transition-all bg-emerald-50 border-emerald-200 text-emerald-950";
            if (pageFreeIcon) pageFreeIcon.innerText = "🎉";
            if (pageFreeText) pageFreeText.innerHTML = "<strong>FREE Delivery Unlocked!</strong> (4+ jars offer)";
            if (pageFreeProgress) {
                pageFreeProgress.className = "h-2 rounded-full transition-all duration-500 bg-emerald-600";
                pageFreeProgress.style.width = "100%";
            }
            if (pageFreeSubtext) pageFreeSubtext.innerText = "Special discount applied: Nationwide shipping charge is ৳0.";
        } else {
            pageFreeBanner.className = "p-3.5 rounded-2xl border transition-all bg-amber-50/90 border-amber-200 text-amber-950";
            if (pageFreeIcon) pageFreeIcon.innerText = "🚚";
            if (pageFreeText) pageFreeText.innerHTML = `Add <strong><span id="freeDeliveryRemaining">${remainingForFree}</span> more jar${remainingForFree > 1 ? 's' : ''}</strong> for <strong>FREE Delivery</strong>!`;
            if (pageFreeProgress) {
                pageFreeProgress.className = "h-2 rounded-full transition-all duration-500 bg-amber-500";
                pageFreeProgress.style.width = `${progressPercent}%`;
            }
            if (pageFreeSubtext) pageFreeSubtext.innerText = "Order 4 or more items to get 100% free delivery nationwide!";
        }
    }
}

// Render dynamic cart items inside Drawer
function renderCartDrawer(items, subtotal) {
    const drawerItems = document.getElementById('cartDrawerItems');
    if (!drawerItems) return;

    const totalItems = items ? items.reduce((sum, itm) => sum + (itm.quantity || 0), 0) : 0;
    updateFreeDeliveryProgress(totalItems);

    if (!items || items.length === 0) {
        drawerItems.innerHTML = `
            <div class="text-center py-12 px-4" id="emptyCartMessage">
                <div class="w-20 h-20 bg-emerald-50 rounded-full flex items-center justify-center mx-auto mb-4 text-3xl">
                    🥒
                </div>
                <h4 class="font-display font-bold text-gray-800 text-lg">Your jar bag is empty!</h4>
                <p class="text-xs text-gray-500 mt-1 mb-6">Choose your favorite homemade pickle jars and add them here.</p>
                <a href="/#pickle-menu" onclick="toggleCartDrawer(false)" class="inline-block bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold px-5 py-2.5 rounded-xl shadow-sm transition">
                    Explore Flavors
                </a>
            </div>
        `;
    } else {
        drawerItems.innerHTML = items.map(item => `
            <div class="flex gap-3.5 p-3 rounded-2xl bg-gray-50/80 border border-gray-100 relative group" id="drawer-item-${item.product_id}">
                <img src="${item.image_url}" alt="${item.name}" class="w-16 h-16 sm:w-20 sm:h-20 object-cover rounded-xl border border-gray-200 bg-white flex-shrink-0">
                <div class="flex-1 min-w-0">
                    <div class="flex items-start justify-between gap-1">
                        <h4 class="font-bold text-sm text-gray-900 truncate">${item.name}</h4>
                        <button onclick="ajaxUpdateCart(${item.product_id}, 'remove')" class="text-gray-400 hover:text-rose-500 text-xs p-1" title="Remove">
                            <i class="fa-solid fa-trash-can"></i>
                        </button>
                    </div>
                    <p class="text-xs text-gray-500">${item.weight}g Jar • ৳${parseFloat(item.price).toFixed(2)}</p>
                    <div class="flex items-center justify-between mt-2.5">
                        <div class="flex items-center border border-gray-200 rounded-lg bg-white overflow-hidden shadow-xs">
                            <button onclick="ajaxUpdateCart(${item.product_id}, 'decrease')" class="px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-100 active:bg-gray-200 font-bold">-</button>
                            <span class="px-3 py-1 text-xs font-bold text-gray-900 border-x border-gray-100" id="drawer-qty-${item.product_id}">${item.quantity}</span>
                            <button onclick="ajaxUpdateCart(${item.product_id}, 'increase')" class="px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-100 active:bg-gray-200 font-bold">+</button>
                        </div>
                        <span class="font-display font-bold text-sm text-emerald-700" id="drawer-total-${item.product_id}">৳${parseFloat(item.total_price).toFixed(2)}</span>
                    </div>
                </div>
            </div>
        `).join('');
    }
}

// AJAX Add To Cart (Adds item smoothly, updates badges & progress bar, shows toast feedback, does NOT auto-open drawer)
async function ajaxAddToCart(productId, quantity = 1, btnEl = null) {
    if (!btnEl && typeof event !== 'undefined' && event && event.currentTarget) {
        btnEl = event.currentTarget;
    }
    
    let originalBtnHTML = '';
    if (btnEl) {
        originalBtnHTML = btnEl.innerHTML;
        btnEl.disabled = true;
        btnEl.innerHTML = '<i class="fa-solid fa-spinner fa-spin text-xs"></i> <span>Adding...</span>';
    }

    const formData = new FormData();
    formData.append('quantity', quantity);
    const token = getCsrfToken();
    if (token) {
        formData.append('csrfmiddlewaretoken', token);
    }

    try {
        const response = await fetch(`/cart/add/${productId}/?format=json`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': token,
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: formData
        });

        if (!response.ok) {
            throw new Error(`Server returned HTTP ${response.status}`);
        }

        const data = await response.json();
        if (data.success) {
            if (typeof fbq === 'function' && data.added_product) {
                const addPrice = parseFloat(data.added_product.price) || 0;
                const addQty = parseInt(data.added_product.quantity, 10) || 1;
                const totalVal = Math.round(addPrice * addQty * 100) / 100;
                fbq('track', 'AddToCart', {
                    content_name: String(data.added_product.name || ''),
                    content_ids: [String(data.added_product.id)],
                    content_type: 'product',
                    value: totalVal,
                    currency: 'BDT'
                });
            }
            updateCartBadges(data.cart_total_items, data.cart_subtotal);
            if (data.items) {
                renderCartDrawer(data.items, data.cart_subtotal);
            }
            showToast(data.message || 'Added to your pickle jar bag!');
            
            if (btnEl) {
                btnEl.innerHTML = '<i class="fa-solid fa-check text-xs"></i> <span>Added!</span>';
                setTimeout(() => {
                    btnEl.innerHTML = originalBtnHTML;
                    btnEl.disabled = false;
                }, 1400);
            }
        } else {
            showToast(data.error || 'Failed to add item to bag');
            if (btnEl) {
                btnEl.innerHTML = originalBtnHTML;
                btnEl.disabled = false;
            }
        }
    } catch (err) {
        console.error('Error adding to cart:', err);
        showToast('Item added to jar bag!');
        if (btnEl) {
            btnEl.innerHTML = originalBtnHTML;
            btnEl.disabled = false;
        }
    }
}

// AJAX Update Cart item quantity (+ / - / remove)
async function ajaxUpdateCart(productId, action) {
    const token = getCsrfToken();
    try {
        const response = await fetch('/cart/update-ajax/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': token,
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({
                product_id: productId,
                action: action
            })
        });

        if (!response.ok) {
            throw new Error(`Server returned HTTP ${response.status}`);
        }

        const data = await response.json();
        if (data.success) {
            updateCartBadges(data.cart_total_items, data.cart_subtotal);

            // If we have the full items list, re-render drawer
            if (data.items) {
                renderCartDrawer(data.items, data.cart_subtotal);
            }

            // Update item quantity in cart page (if on /cart/)
            const pageQty = document.getElementById(`cart-page-qty-${productId}`);
            const pageTotal = document.getElementById(`cart-page-total-${productId}`);
            const pageItem = document.getElementById(`cart-page-item-${productId}`);

            if (data.item_quantity > 0) {
                if (pageQty) pageQty.innerText = data.item_quantity;
                if (pageTotal) pageTotal.innerText = `৳${parseFloat(data.item_total).toFixed(2)}`;
            } else {
                if (pageItem) pageItem.remove();
                if (data.cart_total_items === 0 && window.location.pathname.includes('/cart/')) {
                    location.reload();
                }
            }

            // Update subtotal & total texts on cart page
            const pageSub = document.getElementById('pageCartSubtotal');
            if (pageSub) pageSub.innerText = parseFloat(data.cart_subtotal).toFixed(2);

            const deliveryFee = data.delivery_fee !== undefined ? parseFloat(data.delivery_fee) : (data.cart_total_items >= 4 ? 0.00 : 150.00);
            const pageDelivery = document.getElementById('pageCartDeliveryFee');
            const pageOldFee = document.getElementById('pageCartOldFee');
            const pageDeliveryNote = document.getElementById('pageCartDeliveryNote');

            if (pageDelivery) {
                if (deliveryFee === 0 || data.cart_total_items >= 4) {
                    if (pageOldFee) pageOldFee.classList.remove('hidden');
                    pageDelivery.className = "font-black text-emerald-700 bg-emerald-100 text-xs px-2 py-0.5 rounded-md";
                    pageDelivery.innerText = "FREE (৳0.00)";
                    if (pageDeliveryNote) pageDeliveryNote.innerText = "🎉 Enjoy free door-to-door delivery across Bangladesh!";
                } else {
                    if (pageOldFee) pageOldFee.classList.add('hidden');
                    pageDelivery.className = "font-bold text-emerald-800";
                    pageDelivery.innerText = `৳${deliveryFee.toFixed(2)}`;
                    if (pageDeliveryNote) pageDeliveryNote.innerText = "Flat ৳150 nationwide delivery across Bangladesh (Free on 4+ jars).";
                }
            }

            const pageTot = document.getElementById('pageCartTotal');
            if (pageTot) {
                const total = data.grand_total !== undefined ? parseFloat(data.grand_total) : (parseFloat(data.cart_subtotal) + deliveryFee);
                pageTot.innerText = total.toFixed(2);
            }

            const pageWeight = document.getElementById('pageCartWeightKg');
            if (pageWeight && data.total_weight_kg !== undefined) {
                pageWeight.innerText = data.total_weight_kg;
            }
        }
    } catch (err) {
        console.error('Error updating cart:', err);
    }
}

// Update header and mobile bottom bar badges
function updateCartBadges(count, subtotal) {
    const badge = document.getElementById('cartBadgeCount');
    const mobileBadge = document.getElementById('mobileCartBadge');
    const mobileSubtotal = document.getElementById('mobileCartSubtotal');
    const drawerItemCount = document.getElementById('drawerItemCount');
    const drawerSubtotal = document.getElementById('drawerSubtotal');

    if (badge) {
        badge.innerText = count;
        badge.classList.remove('opacity-75');
        badge.classList.add('scale-125');
        setTimeout(() => badge.classList.remove('scale-125'), 300);
    }
    if (mobileBadge) {
        mobileBadge.innerText = count;
        mobileBadge.classList.add('scale-125');
        setTimeout(() => mobileBadge.classList.remove('scale-125'), 300);
    }
    if (mobileSubtotal && subtotal !== undefined) mobileSubtotal.innerText = parseFloat(subtotal).toFixed(2);
    if (drawerItemCount) drawerItemCount.innerText = count;
    if (drawerSubtotal && subtotal !== undefined) drawerSubtotal.innerText = parseFloat(subtotal).toFixed(2);

    updateFreeDeliveryProgress(count || 0);
}

// Attach event listener for product detail page add to cart form if present
document.addEventListener('DOMContentLoaded', () => {
    const productDetailForm = document.querySelector('form[action*="/cart/add/"]');
    if (productDetailForm) {
        productDetailForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const action = productDetailForm.getAttribute('action');
            const match = action.match(/\/cart\/add\/(\d+)\//);
            const qtyInput = document.getElementById('productQtyInput');
            const quantity = qtyInput ? parseInt(qtyInput.value) || 1 : 1;
            
            if (match && match[1]) {
                ajaxAddToCart(match[1], quantity);
            } else {
                productDetailForm.submit();
            }
        });
    }
});

