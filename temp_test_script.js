

let manualDeliveryFeeUserOverridden = false;



function openManualOrderModal() {

    manualDeliveryFeeUserOverridden = false;

    document.getElementById('manualOrderModal').classList.remove('hidden');

    updateRemoveButtonsState();

    calculateManualOrderTotal();

}

function closeManualOrderModal() {

    document.getElementById('manualOrderModal').classList.add('hidden');

}



function addManualOrderItem() {

    const container = document.getElementById('manualOrderItemsContainer');

    if (!container) return;

    const rows = container.getElementsByClassName('manual-order-item-row');

    if (rows.length === 0) return;



    const clone = rows[0].cloneNode(true);

    const qtyInput = clone.querySelector('.item-qty');

    if (qtyInput) qtyInput.value = 1;



    const select = clone.querySelector('.product-select');

    if (select && select.options.length > rows.length) {

        select.selectedIndex = rows.length;

    }



    container.appendChild(clone);

    updateRemoveButtonsState();

    calculateManualOrderTotal();

}



function removeManualOrderItem(btn) {

    const container = document.getElementById('manualOrderItemsContainer');

    if (!container) return;

    const rows = container.getElementsByClassName('manual-order-item-row');

    if (rows.length > 1) {

        btn.closest('.manual-order-item-row').remove();

    }

    updateRemoveButtonsState();

    calculateManualOrderTotal();

}



function updateRemoveButtonsState() {

    const container = document.getElementById('manualOrderItemsContainer');

    if (!container) return;

    const rows = container.getElementsByClassName('manual-order-item-row');

    const btns = container.querySelectorAll('.remove-item-btn');

    btns.forEach(b => {

        if (rows.length <= 1) {

            b.classList.add('opacity-30', 'cursor-not-allowed');

            b.disabled = true;

        } else {

            b.classList.remove('opacity-30', 'cursor-not-allowed');

            b.disabled = false;

        }

    });

}



function calculateManualOrderTotal(isManualFeeChange = false) {

    const container = document.getElementById('manualOrderItemsContainer');

    if (!container) return;

    const rows = container.getElementsByClassName('manual-order-item-row');

    let subtotal = 0;

    let totalJars = 0;



    for (let row of rows) {

        const select = row.querySelector('.product-select');

        const qtyInput = row.querySelector('.item-qty');

        const subtotalSpan = row.querySelector('.item-subtotal');

        

        let qty = parseInt(qtyInput ? qtyInput.value : 1) || 0;

        if (qty < 1) qty = 1;

        totalJars += qty;



        const selectedOpt = select && select.selectedIndex >= 0 ? select.options[select.selectedIndex] : null;

        const price = selectedOpt ? parseFloat(selectedOpt.getAttribute('data-price') || 0) : 0;

        const lineTotal = price * qty;

        subtotal += lineTotal;



        if (subtotalSpan) {

            subtotalSpan.textContent = '৳' + lineTotal.toFixed(0);

        }

    }



    const deliveryInput = document.getElementById('manualDeliveryFeeInput');

    const freeBadge = document.getElementById('manualFreeDeliveryBadge');

    

    if (isManualFeeChange) {

        manualDeliveryFeeUserOverridden = true;

    }



    if (!manualDeliveryFeeUserOverridden && deliveryInput) {

        if (totalJars >= 4) {

            deliveryInput.value = 0;

        } else {

            deliveryInput.value = 150;

        }

    }



    let deliveryFee = deliveryInput ? (parseFloat(deliveryInput.value) || 0) : (totalJars >= 4 ? 0 : 150);

    if (deliveryFee < 0) deliveryFee = 0;



    if (freeBadge) {

        if (totalJars >= 4 || deliveryFee === 0) {

            freeBadge.classList.remove('hidden');

        } else {

            freeBadge.classList.add('hidden');

        }

    }



    const grandTotal = subtotal + deliveryFee;



    const countEl = document.getElementById('manualSummaryItemCount');

    const subtotalEl = document.getElementById('manualSummarySubtotal');

    const deliveryEl = document.getElementById('manualSummaryDelivery');

    const grandTotalEl = document.getElementById('manualSummaryGrandTotal');



    if (countEl) countEl.textContent = totalJars;

    if (subtotalEl) subtotalEl.textContent = '৳' + subtotal.toFixed(0);

    if (deliveryEl) {

        if (deliveryFee === 0 || totalJars >= 4) {

            deliveryEl.innerHTML = '<span class="text-emerald-700 font-black">FREE (৳0)</span>';

        } else {

            deliveryEl.textContent = '৳' + deliveryFee.toFixed(0);

        }

    }

    if (grandTotalEl) grandTotalEl.textContent = '৳' + grandTotal.toFixed(0);

}



function openDeleteOrderModal(orderNumber, customerName) {

    document.getElementById('del_order_number').textContent = '#' + orderNumber;

    document.getElementById('del_order_customer').textContent = customerName;

    document.getElementById('deleteOrderForm').action = '/dashboard/orders/delete/' + orderNumber + '/';

    document.getElementById('deleteOrderModal').classList.remove('hidden');

}

function closeDeleteOrderModal() {

    document.getElementById('deleteOrderModal').classList.add('hidden');

}



let currentPathaoOrderNumber = '';

function openPathaoModal(orderNumber, customerName, customerPhone, deliveryAddress, deliveryCity, deliveryZone, totalAmount, totalJars, paymentStatus) {

    currentPathaoOrderNumber = orderNumber;

    document.getElementById('pathao_modal_order_number').textContent = '#' + orderNumber;

    document.getElementById('pathao_modal_customer_name').textContent = customerName;

    document.getElementById('pathao_modal_customer_phone').textContent = customerPhone;

    document.getElementById('pathao_modal_address').textContent = deliveryAddress + (deliveryCity ? ', ' + deliveryCity : '');

    document.getElementById('pathao_modal_zone').textContent = deliveryZone || deliveryCity;

    document.getElementById('pathao_modal_items').textContent = totalJars + ' Jar(s)';

    

    const codSpan = document.getElementById('pathao_modal_cod_amount');

    const payStatusSpan = document.getElementById('pathao_modal_payment_status');

    if (paymentStatus === 'PAID') {

        codSpan.textContent = '৳0 (Already Paid)';

        codSpan.className = 'font-display font-black text-sm text-emerald-600';

        payStatusSpan.textContent = 'Payment: PAID';

    } else {

        codSpan.textContent = '৳' + totalAmount;

        codSpan.className = 'font-display font-black text-sm text-[#ea1d24]';

        payStatusSpan.textContent = 'Payment: UNPAID (Collect COD)';

    }



    const ptBtn = document.getElementById('pathaoSubmitBtn');

    if (ptBtn) {

        ptBtn.disabled = false;

        ptBtn.classList.remove('opacity-70', 'cursor-not-allowed');

        ptBtn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> <span>Confirm & Send to Pathao</span>';

    }



    document.getElementById('pathaoDispatchForm').action = '/dashboard/order/' + orderNumber + '/dispatch-pathao/';

    document.getElementById('pathaoDispatchModal').classList.remove('hidden');

}

function closePathaoModal() {

    document.getElementById('pathaoDispatchModal').classList.add('hidden');

}

let currentSteadfastOrderNumber = '';

function openSteadfastModal(orderNumber, customerName, customerPhone, deliveryAddress, deliveryCity, deliveryZone, totalAmount, totalJars, paymentStatus) {

    currentSteadfastOrderNumber = orderNumber;

    document.getElementById('steadfast_modal_order_number').textContent = '#' + orderNumber;

    document.getElementById('steadfast_modal_customer_name').textContent = customerName;

    document.getElementById('steadfast_modal_customer_phone').textContent = customerPhone;

    document.getElementById('steadfast_modal_address').textContent = deliveryAddress + (deliveryCity ? ', ' + deliveryCity : '');

    document.getElementById('steadfast_modal_zone').textContent = deliveryZone || deliveryCity;

    document.getElementById('steadfast_modal_items').textContent = totalJars + ' Jar(s)';

    

    const codSpan = document.getElementById('steadfast_modal_cod_amount');

    const payStatusSpan = document.getElementById('steadfast_modal_payment_status');

    if (paymentStatus === 'PAID') {

        codSpan.textContent = '৳0 (Already Paid)';

        codSpan.className = 'font-display font-black text-sm text-emerald-600';

        payStatusSpan.textContent = 'Payment: PAID';

    } else {

        codSpan.textContent = '৳' + totalAmount;

        codSpan.className = 'font-display font-black text-sm text-cyan-800';

        payStatusSpan.textContent = 'Payment: UNPAID (Collect COD)';

    }



    const sfBtn = document.getElementById('steadfastSubmitBtn');

    if (sfBtn) {

        sfBtn.disabled = false;

        sfBtn.classList.remove('opacity-70', 'cursor-not-allowed');

        sfBtn.innerHTML = '<i class="fa-solid fa-truck-fast"></i> <span>Confirm & Send to Steadfast</span>';

    }



    document.getElementById('steadfastDispatchForm').action = '/dashboard/order/' + orderNumber + '/dispatch-steadfast/';

    document.getElementById('steadfastDispatchModal').classList.remove('hidden');

}

function closeSteadfastModal() {

    document.getElementById('steadfastDispatchModal').classList.add('hidden');

}



// Courier submit loading states

document.addEventListener('DOMContentLoaded', function() {

    const sfForm = document.getElementById('steadfastDispatchForm');

    if (sfForm) {

        sfForm.addEventListener('submit', function() {

            const btn = document.getElementById('steadfastSubmitBtn');

            if (btn) {

                btn.disabled = true;

                btn.classList.add('opacity-70', 'cursor-not-allowed');

                btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> <span>Sending to Steadfast API...</span>';

            }

            if (currentSteadfastOrderNumber) {

                const tableBtn = document.getElementById('sf_btn_' + currentSteadfastOrderNumber);

                if (tableBtn) {

                    tableBtn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin text-cyan-700"></i>';

                }

            }

        });

    }



    const ptForm = document.getElementById('pathaoDispatchForm');

    if (ptForm) {

        ptForm.addEventListener('submit', function() {

            const btn = document.getElementById('pathaoSubmitBtn');

            if (btn) {

                btn.disabled = true;

                btn.classList.add('opacity-70', 'cursor-not-allowed');

                btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> <span>Sending to Pathao API...</span>';

            }

            if (currentPathaoOrderNumber) {

                const tableBtn = document.getElementById('pathao_btn_' + currentPathaoOrderNumber);

                if (tableBtn) {

                    tableBtn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin text-red-600"></i>';

                }

            }

        });

    }

});



/* ========================================================

   STEADFAST FRAUD CHECK LIVE MODAL HANDLER (FAST & OPTIMIZED)

   ======================================================== */

const clientOrdersFraudCache = {};

let currentFraudModalContext = { phone: '', customerName: '', orderNumber: '' };



// Background hover prefetch so clicking opens instantly with 0ms wait

function prefetchFraud(phone) {

    if (!phone) return;

    const clean = phone.replace(/[^0-9]/g, '');

    const cleanPhone = clean.length > 11 ? clean.slice(-11) : clean;

    if (clientOrdersFraudCache[cleanPhone]) return;



    fetch(`/dashboard/api/fraud-check/?phone=${encodeURIComponent(cleanPhone)}`)

        .then(r => r.json())

        .then(data => {

            if (data.success) {

                clientOrdersFraudCache[cleanPhone] = data;

            }

        })

        .catch(() => {});

}



function refreshCurrentFraudModal() {

    if (currentFraudModalContext.phone) {

        openFraudModal(

            currentFraudModalContext.phone, 

            currentFraudModalContext.customerName, 

            currentFraudModalContext.orderNumber, 

            true

        );

    }

}



async function openFraudModal(phone, customerName, orderNumber, isForce = false) {

    currentFraudModalContext = { phone, customerName, orderNumber };



    document.getElementById('fraud_modal_customer_name').textContent = customerName || 'Customer';

    document.getElementById('fraud_modal_order_number').textContent = orderNumber ? '#' + orderNumber : '';

    document.getElementById('fraud_modal_phone').textContent = phone;



    const clean = phone.replace(/[^0-9]/g, '');

    const last10 = clean.slice(-10);

    const cleanPhone = clean.length > 11 ? clean.slice(-11) : clean;



    document.getElementById('fraud_modal_call_btn').href = 'tel:' + phone;

    document.getElementById('fraud_modal_wa_btn').href = `https://wa.me/880${last10}?text=Hello%20${encodeURIComponent(customerName || '')},%20from%20Pickpickles`;



    const modal = document.getElementById('fraudCheckModal');

    const content = document.getElementById('fraudModalContent');

    const badge = document.getElementById('fraud_modal_cache_badge');

    const recheckBtn = document.getElementById('fraud_modal_recheck_btn');

    modal.classList.remove('hidden');



    // 1. Instant Render from Memory Cache (0ms) if not forced

    if (!isForce && clientOrdersFraudCache[cleanPhone]) {

        renderOrdersFraudContent(clientOrdersFraudCache[cleanPhone], content, badge);

        return;

    }



    if (badge) badge.classList.add('hidden');

    if (recheckBtn) {

        recheckBtn.disabled = true;

        recheckBtn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin text-[10px]"></i> <span>Checking...</span>';

    }



    content.innerHTML = `

        <div class="py-8 text-center space-y-2">

            <i class="fa-solid fa-circle-notch fa-spin text-cyan-600 text-2xl"></i>

            <p class="text-xs text-gray-600 font-bold">Connecting to Steadfast Courier API & Analyzing History...</p>

        </div>

    `;



    try {

        const url = `/dashboard/api/fraud-check/?phone=${encodeURIComponent(phone)}${isForce ? '&force=1' : ''}`;

        const res = await fetch(url);

        const data = await res.json();



        if (data.success) {

            clientOrdersFraudCache[cleanPhone] = data;

            renderOrdersFraudContent(data, content, badge);

        } else {

            content.innerHTML = `

                <div class="p-4 rounded-2xl bg-rose-50 border border-rose-200 text-rose-800 text-xs">

                    <i class="fa-solid fa-circle-xmark text-rose-600"></i>

                    <span class="font-bold">Error:</span> ${data.message || 'Failed to fetch fraud record.'}

                </div>

            `;

        }

    } catch (e) {

        content.innerHTML = `

            <div class="p-4 rounded-2xl bg-rose-50 border border-rose-200 text-rose-800 text-xs">

                <i class="fa-solid fa-circle-xmark text-rose-600"></i>

                <span class="font-bold">Network Error:</span> Failed to connect to server.

            </div>

        `;

    } finally {

        if (recheckBtn) {

            recheckBtn.disabled = false;

            recheckBtn.innerHTML = '<i class="fa-solid fa-rotate text-[10px]"></i> <span>Re-check Live</span>';

        }

    }

}



let isModalPhoneBlocked = false;



function updateBlacklistBtnStyle(isBlocked) {

    isModalPhoneBlocked = !!isBlocked;

    const btn = document.getElementById('fraud_modal_blacklist_btn');

    const txt = document.getElementById('fraud_modal_blacklist_txt');

    if (!btn || !txt) return;

    

    if (isBlocked) {

        btn.className = "bg-rose-700 hover:bg-rose-800 text-white text-xs font-black px-2.5 py-1 rounded-xl shadow-xs transition inline-flex items-center gap-1 cursor-pointer";

        btn.innerHTML = '<i class="fa-solid fa-ban text-[10px]"></i> <span id="fraud_modal_blacklist_txt">Unblock Phone</span>';

    } else {

        btn.className = "bg-rose-100 hover:bg-rose-200 text-rose-800 text-xs font-bold px-2.5 py-1 rounded-xl border border-rose-300 shadow-2xs transition inline-flex items-center gap-1 cursor-pointer";

        btn.innerHTML = '<i class="fa-solid fa-ban text-[10px]"></i> <span id="fraud_modal_blacklist_txt">Block Number</span>';

    }

}



function toggleBlacklistFromModal() {

    if (!currentFraudModalContext.phone) return;



    const modal = document.getElementById('ordersBlacklistConfirmModal');

    const iconBox = document.getElementById('ordersBlModalIconBox');

    const icon = document.getElementById('ordersBlModalIcon');

    const title = document.getElementById('ordersBlModalTitle');

    const msg = document.getElementById('ordersBlModalMessage');

    const nameEl = document.getElementById('ordersBlModalName');

    const phoneEl = document.getElementById('ordersBlModalPhone');

    const confirmBtn = document.getElementById('ordersBlModalConfirmBtn');

    const btnText = document.getElementById('ordersBlModalBtnText');



    if (nameEl) nameEl.textContent = currentFraudModalContext.customerName || 'Customer';

    if (phoneEl) phoneEl.textContent = currentFraudModalContext.phone;



    if (isModalPhoneBlocked) {

        // Recover / Unblock State

        if (iconBox) iconBox.className = "w-10 h-10 rounded-2xl bg-emerald-100 text-emerald-600 flex items-center justify-center text-lg shrink-0";

        if (icon) icon.className = "fa-solid fa-shield-heart";

        if (title) title.textContent = "Confirm Customer Unblock (কাস্টমার আনব্লক)";

        if (msg) msg.innerHTML = "আপনি কি নিশ্চিত যে এই কাস্টমারকে <strong>আনব্লক (Recover)</strong> করতে চান? আনব্লক করলে গ্রাহক আবার ওয়েবসাইটে Cash on Delivery অর্ডার দিতে পারবে।";

        if (confirmBtn) confirmBtn.className = "px-5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-black text-xs transition shadow-md cursor-pointer flex items-center justify-center gap-1.5";

        if (btnText) btnText.textContent = "Yes, Unblock & Recover (আনব্লক করুন)";

    } else {

        // Block State

        if (iconBox) iconBox.className = "w-10 h-10 rounded-2xl bg-rose-100 text-rose-600 flex items-center justify-center text-lg shrink-0";

        if (icon) icon.className = "fa-solid fa-ban";

        if (title) title.textContent = "Confirm Customer Block (কাস্টমার ব্লক)";

        if (msg) msg.innerHTML = "আপনি কি নিশ্চিত যে এই কাস্টমারকে <strong>ব্লক (Blacklist)</strong> করতে চান? ব্লক করা হলে এই নাম্বার থেকে কোনো নতুন Cash on Delivery অর্ডার গ্রহণ করা হবে না।";

        if (confirmBtn) confirmBtn.className = "px-5 py-2.5 rounded-xl bg-rose-600 hover:bg-rose-700 text-white font-black text-xs transition shadow-md cursor-pointer flex items-center justify-center gap-1.5";

        if (btnText) btnText.textContent = "Yes, Block Number (ব্লক করুন)";

    }



    modal?.classList.remove('hidden');

}



function closeOrdersBlacklistConfirmModal() {

    document.getElementById('ordersBlacklistConfirmModal')?.classList.add('hidden');

}



async function executeOrdersBlacklistToggle() {

    const confirmBtn = document.getElementById('ordersBlModalConfirmBtn');

    const originalText = confirmBtn ? confirmBtn.innerHTML : '';

    if (confirmBtn) {

        confirmBtn.disabled = true;

        confirmBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin text-xs"></i> Processing...';

    }



    try {

        const formData = new FormData();

        formData.append('phone', currentFraudModalContext.phone);

        formData.append('customer_name', currentFraudModalContext.customerName || '');

        formData.append('reason', 'Blocked via Orders Queue');

        

        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || 

                          document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

                          

        const res = await fetch('/dashboard/api/toggle-blacklist/', {

            method: 'POST',

            headers: {

                'X-CSRFToken': csrfToken,

                'X-Requested-With': 'XMLHttpRequest'

            },

            body: formData

        });

        const data = await res.json();

        if (data.success) {

            updateBlacklistBtnStyle(data.is_blacklisted);

            const clean = currentFraudModalContext.phone.replace(/[^0-9]/g, '');

            const cleanPhone = clean.length > 11 ? clean.slice(-11) : clean;

            if (clientOrdersFraudCache[cleanPhone]) {

                clientOrdersFraudCache[cleanPhone].is_blacklisted = data.is_blacklisted;

            }

            closeOrdersBlacklistConfirmModal();

            const notifMsg = data.is_blacklisted ? 

                `🚫 নাম্বার <strong>${currentFraudModalContext.phone}</strong> সফলভাবে ব্লক করা হয়েছে।` : 

                `✅ নাম্বার <strong>${currentFraudModalContext.phone}</strong> সফলভাবে আনব্লক (Recover) করা হয়েছে।`;

            if (typeof showToast === 'function') {

                showToast(notifMsg, data.is_blacklisted ? 'error' : 'success', 4000);

            }

        } else {

            if (typeof showToast === 'function') {

                showToast(data.error || 'Failed to update blacklist', 'error');

            }

        }

    } catch (err) {

        if (typeof showToast === 'function') {

            showToast('Network error while toggling blacklist', 'error');

        }

    } finally {

        if (confirmBtn) {

            confirmBtn.disabled = false;

            confirmBtn.innerHTML = originalText;

        }

    }

}



function renderOrdersFraudContent(data, content, badge) {

    if (badge) {

        if (data.from_cache) {

            badge.classList.remove('hidden');

        } else {

            badge.classList.add('hidden');

        }

    }



    // Update Blacklist Button state

    updateBlacklistBtnStyle(data.is_blacklisted);



    const sf = data.steadfast || {};

    const local = data.local || {};



    let sfHtml = '';

    if (sf.success) {

        let statsGrid = '';

        if (sf.delivery_ratio !== null && sf.delivery_ratio !== undefined) {

            statsGrid = `

                <div class="grid grid-cols-4 gap-1.5 text-center">

                    <div class="bg-white/90 p-2 rounded-xl border border-current/10 shadow-2xs">

                        <span class="text-[10px] text-emerald-700 block font-bold">Delivery Rate</span>

                        <strong class="text-sm sm:text-base font-black text-emerald-700">${sf.success_rate}%</strong>

                    </div>

                    <div class="bg-white/90 p-2 rounded-xl border border-current/10 shadow-2xs">

                        <span class="text-[10px] text-rose-700 block font-bold">Return Rate</span>

                        <strong class="text-sm sm:text-base font-black text-rose-700">${sf.return_rate}%</strong>

                    </div>

                    <div class="bg-white/90 p-2 rounded-xl border border-current/10 shadow-2xs">

                        <span class="text-[10px] opacity-75 block font-bold">Activity</span>

                        <strong class="text-xs sm:text-sm font-black text-gray-900">${sf.volume_band_display || (sf.volume_band ? sf.volume_band.toUpperCase() : '--')}</strong>

                    </div>

                    <div class="bg-white/90 p-2 rounded-xl border border-current/10 shadow-2xs">

                        <span class="text-[10px] ${sf.total_reports > 0 ? 'text-rose-700' : 'text-gray-500'} block font-bold">Reports</span>

                        <strong class="text-sm sm:text-base font-black ${sf.total_reports > 0 ? 'text-rose-700' : 'text-gray-900'}">${sf.total_reports || 0}</strong>

                    </div>

                </div>

            `;

        } else if (sf.total_parcels > 0) {

            statsGrid = `

                <div class="grid grid-cols-3 gap-2 text-center">

                    <div class="bg-white/90 p-2 rounded-xl border border-current/10 shadow-2xs">

                        <span class="text-[10px] opacity-75 block font-bold">Steadfast Parcels</span>

                        <strong class="text-base font-black text-gray-900">${sf.total_parcels}</strong>

                    </div>

                    <div class="bg-white/90 p-2 rounded-xl border border-current/10 shadow-2xs">

                        <span class="text-[10px] text-emerald-700 block font-bold">Delivered</span>

                        <strong class="text-base font-black text-emerald-700">${sf.total_delivered}</strong>

                    </div>

                    <div class="bg-white/90 p-2 rounded-xl border border-current/10 shadow-2xs">

                        <span class="text-[10px] text-rose-700 block font-bold">Cancelled / Return</span>

                        <strong class="text-base font-black text-rose-700">${sf.total_cancelled}</strong>

                    </div>

                </div>

            `;

        } else {

            statsGrid = `

                <div class="grid grid-cols-3 gap-2 text-center">

                    <div class="bg-white/90 p-2 rounded-xl border border-current/10 shadow-2xs">

                        <span class="text-[10px] opacity-75 block font-bold">Activity Status</span>

                        <strong class="text-xs sm:text-sm font-black text-gray-900">${sf.volume_band_display || 'New / No Record'}</strong>

                    </div>

                    <div class="bg-white/90 p-2 rounded-xl border border-current/10 shadow-2xs">

                        <span class="text-[10px] text-emerald-700 block font-bold">Delivery Success</span>

                        <strong class="text-sm sm:text-base font-black text-emerald-700">100%</strong>

                    </div>

                    <div class="bg-white/90 p-2 rounded-xl border border-current/10 shadow-2xs">

                        <span class="text-[10px] text-gray-500 block font-bold">Reports</span>

                        <strong class="text-sm sm:text-base font-black text-gray-900">${sf.total_reports || 0}</strong>

                    </div>

                </div>

            `;

        }



        let categoriesHtml = '';

        if (sf.fraud_categories && sf.fraud_categories.length > 0) {

            categoriesHtml = `

                <div class="flex items-center gap-1.5 flex-wrap pt-1">

                    <span class="text-[10px] font-bold text-rose-900 uppercase">Merchant Tags:</span>

                    ${sf.fraud_categories.map(c => `<span class="bg-rose-200/80 text-rose-900 font-bold text-[10px] px-2 py-0.5 rounded border border-rose-300 shadow-2xs">${c}</span>`).join('')}

                </div>

            `;

        }



        sfHtml = `

            <div class="p-4 rounded-2xl border ${sf.badge_class} space-y-2.5">

                <div class="flex items-center justify-between gap-2 flex-wrap">

                    <span class="font-extrabold flex items-center gap-1.5 text-xs">

                        <i class="fa-solid fa-truck-fast text-cyan-700"></i>

                        <span>Steadfast Network: ${sf.risk_title}</span>

                    </span>

                    <span class="text-[10px] font-black uppercase tracking-wider bg-white/90 px-2 py-0.5 rounded shadow-2xs">

                        ${sf.success_rate}% Delivery Rate

                    </span>

                </div>



                ${statsGrid}

                ${categoriesHtml}



                <p class="text-xs leading-relaxed opacity-90 pt-1">

                    ${sf.risk_desc}

                </p>

            </div>

        `;

    } else {

        sfHtml = `

            <div class="p-3.5 rounded-2xl bg-amber-50 border border-amber-200 text-amber-900 text-xs space-y-1">

                <div class="font-bold flex items-center gap-1.5">

                    <i class="fa-solid fa-circle-exclamation text-amber-600"></i>

                    <span>Steadfast API Notice:</span>

                </div>

                <p class="text-[11px] text-amber-800">${sf.message || 'Steadfast API not reachable or credentials missing.'}</p>

            </div>

        `;

    }



    const localHtml = `

        <div class="p-4 rounded-2xl border border-gray-200 bg-gray-50/80 space-y-2.5">

            <div class="flex items-center justify-between gap-2 flex-wrap">

                <span class="font-extrabold flex items-center gap-1.5 text-xs text-gray-800">

                    <i class="fa-solid fa-store text-brand-700"></i>

                    <span>Pickpickles Store History</span>

                </span>

                <span class="text-[10px] font-black uppercase tracking-wider bg-white px-2 py-0.5 rounded border border-gray-200 shadow-2xs">

                    ${local.success_rate}% Store Success

                </span>

            </div>



            <div class="grid grid-cols-4 gap-2 text-center text-xs">

                <div class="bg-white p-2 rounded-xl border border-gray-200 shadow-2xs">

                    <span class="text-[10px] text-gray-500 block font-bold">Orders</span>

                    <strong class="text-sm font-black text-gray-900">${local.total_orders}</strong>

                </div>

                <div class="bg-white p-2 rounded-xl border border-gray-200 shadow-2xs">

                    <span class="text-[10px] text-emerald-700 block font-bold">Delivered</span>

                    <strong class="text-sm font-black text-emerald-700">${local.delivered_count}</strong>

                </div>

                <div class="bg-white p-2 rounded-xl border border-gray-200 shadow-2xs">

                    <span class="text-[10px] text-rose-700 block font-bold">Cancelled</span>

                    <strong class="text-sm font-black text-rose-700">${local.cancelled_count}</strong>

                </div>

                <div class="bg-white p-2 rounded-xl border border-gray-200 shadow-2xs">

                    <span class="text-[10px] text-brand-700 block font-bold">Total Spent</span>

                    <strong class="text-sm font-black text-brand-700">৳${local.total_spent.toLocaleString()}</strong>

                </div>

            </div>

        </div>

    `;



    content.innerHTML = sfHtml + localHtml;

}



function closeFraudModal() {

    document.getElementById('fraudCheckModal').classList.add('hidden');

}



/* ========================================================

   MOBILE & TABLET VIEW SWITCHER (CARDS VS TABLE)

   ======================================================== */

function setOrdersViewMode(mode) {

    const cardsView = document.getElementById('ordersMobileCardView');

    const tableView = document.getElementById('ordersDesktopTableView');

    const btnCards = document.getElementById('btnViewCards');

    const btnTable = document.getElementById('btnViewTable');



    if (!cardsView || !tableView) return;



    if (mode === 'table') {

        cardsView.classList.add('hidden');

        cardsView.classList.remove('block');

        tableView.classList.remove('hidden');

        tableView.classList.add('block');

        if (btnTable) {

            btnTable.className = "px-2.5 py-1 rounded-lg font-bold transition flex items-center gap-1.5 bg-brand-700 text-white shadow-xs";

        }

        if (btnCards) {

            btnCards.className = "px-2.5 py-1 rounded-lg font-bold transition flex items-center gap-1.5 bg-gray-100 text-gray-600 hover:text-gray-900";

        }

        try { sessionStorage.setItem('pickpickles_orders_view_mode', 'table'); } catch(e) {}

    } else {

        cardsView.classList.remove('hidden');

        cardsView.classList.add('block');

        tableView.classList.add('hidden');

        tableView.classList.remove('block');

        if (!tableView.classList.contains('lg:block')) {

            tableView.classList.add('lg:block');

        }

        if (btnCards) {

            btnCards.className = "px-2.5 py-1 rounded-lg font-bold transition flex items-center gap-1.5 bg-brand-700 text-white shadow-xs";

        }

        if (btnTable) {

            btnTable.className = "px-2.5 py-1 rounded-lg font-bold transition flex items-center gap-1.5 bg-gray-100 text-gray-600 hover:text-gray-900";

        }

        try { sessionStorage.setItem('pickpickles_orders_view_mode', 'cards'); } catch(e) {}

    }

}



document.addEventListener('DOMContentLoaded', function() {

    try {

        // Clear old stale localStorage setting if any so mobile users always default to cards

        localStorage.removeItem('pickpickles_orders_view_mode');

        const sessionMode = sessionStorage.getItem('pickpickles_orders_view_mode');

        if (window.innerWidth < 1024 && sessionMode === 'table') {

            setOrdersViewMode('table');

        }

    } catch(e) {}

});



/* ========================================================

   BULK ORDER SELECTION & WHATSAPP BROADCAST HANDLER

   ======================================================== */

let bulkSelectedOrdersQueue = [];



document.addEventListener('change', function(e) {

    if (e.target && e.target.classList.contains('order-select-checkbox')) {

        const orderNum = e.target.dataset.orderNumber;

        const isChecked = e.target.checked;

        if (orderNum) {

            document.querySelectorAll(`.order-select-checkbox[data-order-number="${orderNum}"]`).forEach(cb => {

                cb.checked = isChecked;

            });

        }

        updateSelectedOrdersBar();

    }

});



function getUniqueSelectedOrderCheckboxes() {

    const seen = new Set();

    const unique = [];

    document.querySelectorAll('.order-select-checkbox:checked').forEach(cb => {

        const orderNum = cb.dataset.orderNumber || cb.value;

        if (orderNum && !seen.has(orderNum)) {

            seen.add(orderNum);

            unique.push(cb);

        }

    });

    return unique;

}



function submitBulkStatusChange(e) {

    const select = document.getElementById('bulkStatusSelect');

    const hiddenInput = document.getElementById('bulkStatusOrderNumbers');

    if (!select || !select.value) {

        e.preventDefault();

        alert('Please select a target status from the dropdown first.');

        return false;

    }

    const uniqueChecked = getUniqueSelectedOrderCheckboxes();

    if (uniqueChecked.length === 0) {

        e.preventDefault();

        alert('Please select at least one order.');

        return false;

    }

    hiddenInput.value = uniqueChecked.map(cb => cb.dataset.orderNumber || cb.value).join(',');

    return true;

}



function toggleSelectAllOrders(masterCheckbox) {

    const isChecked = masterCheckbox.checked;

    document.querySelectorAll('.select-all-orders-toggle').forEach(el => {

        el.checked = isChecked;

    });

    const checkboxes = document.querySelectorAll('.order-select-checkbox');

    checkboxes.forEach(cb => {

        cb.checked = isChecked;

    });

    updateSelectedOrdersBar();

}



function selectOnlyShippedOrders() {

    const checkboxes = document.querySelectorAll('.order-select-checkbox');

    let count = 0;

    checkboxes.forEach(cb => {

        if (cb.dataset.status === 'OUT_FOR_DELIVERY') {

            cb.checked = true;

            count++;

        } else {

            cb.checked = false;

        }

    });

    const isAll = (count > 0 && count === checkboxes.length);

    document.querySelectorAll('.select-all-orders-toggle').forEach(el => {

        el.checked = isAll;

    });

    updateSelectedOrdersBar();

}



function clearOrderSelection() {

    const checkboxes = document.querySelectorAll('.order-select-checkbox');

    checkboxes.forEach(cb => {

        cb.checked = false;

    });

    document.querySelectorAll('.select-all-orders-toggle').forEach(el => {

        el.checked = false;

    });

    updateSelectedOrdersBar();

}



function updateSelectedOrdersBar() {

    const checkboxes = getUniqueSelectedOrderCheckboxes();

    const bar = document.getElementById('bulkActionBar');

    const countSpan = document.getElementById('bulkBarCount');

    const topBadge = document.getElementById('topPackListBadge');

    const count = checkboxes.length;



    if (countSpan) countSpan.textContent = count;

    if (topBadge) {

        topBadge.textContent = count;

        if (count > 0) {

            topBadge.classList.remove('hidden');

        } else {

            topBadge.classList.add('hidden');

        }

    }



    if (bar) {

        if (count > 0) {

            bar.classList.remove('hidden');

            bar.style.display = 'block';

            bar.style.opacity = '1';

            bar.style.transform = 'translateY(0)';

            bar.style.pointerEvents = 'auto';

            requestAnimationFrame(() => {

                bar.classList.remove('translate-y-4', 'opacity-0');

            });

        } else {

            bar.classList.add('translate-y-4', 'opacity-0');

            bar.style.opacity = '0';

            bar.style.transform = 'translateY(16px)';

            bar.style.pointerEvents = 'none';

            setTimeout(() => {

                if (getUniqueSelectedOrderCheckboxes().length === 0) {

                    bar.classList.add('hidden');

                    bar.style.display = 'none';

                }

            }, 300);

        }

    }

}



let currentPackingData = {

    totalJars: 0,

    flavors: {},

    orders: [],

    totalCOD: 0

};



function openBulkPackingModal() {

    const checkedBoxes = getUniqueSelectedOrderCheckboxes();

    if (checkedBoxes.length === 0) {

        alert('অনুগ্রহ করে অন্তত ১টি অর্ডার সিলেক্ট করুন।');

        return;

    }



    const flavors = {};

    let totalJars = 0;

    let totalCOD = 0;

    const orders = [];



    checkedBoxes.forEach(cb => {

        let items = [];

        try {

            items = JSON.parse(cb.dataset.items || '[]');

        } catch(e) {

            items = [];

        }



        let orderJarCount = 0;

        items.forEach(itm => {

            const name = (itm.name || 'Artisanal Pickle Jar').trim();

            const qty = parseInt(itm.qty, 10) || 1;

            flavors[name] = (flavors[name] || 0) + qty;

            totalJars += qty;

            orderJarCount += qty;

        });



        const amount = parseFloat(cb.dataset.amount) || 0;

        totalCOD += amount;



        orders.push({

            orderNumber: cb.dataset.orderNumber || cb.value,

            customerName: cb.dataset.customerName || 'Customer',

            phone: cb.dataset.phone || '',

            city: cb.dataset.city || '',

            address: cb.dataset.address || '',

            amount: amount,

            jarCount: orderJarCount,

            items: items

        });

    });



    currentPackingData = { totalJars, flavors, orders, totalCOD };



    // Render Stats

    const badgeEl = document.getElementById('bulkPackingOrderCountBadge');

    if (badgeEl) badgeEl.innerText = `${orders.length} Orders Selected`;

    const jarsEl = document.getElementById('bulkPackingTotalJars');

    if (jarsEl) jarsEl.innerText = totalJars;

    const flavorCntEl = document.getElementById('bulkPackingFlavorCount');

    if (flavorCntEl) flavorCntEl.innerText = Object.keys(flavors).length;

    const codEl = document.getElementById('bulkPackingTotalCOD');

    if (codEl) codEl.innerText = totalCOD.toFixed(0);



    // Render Flavors

    const flavorsContainer = document.getElementById('bulkPackingFlavorsList');

    if (flavorsContainer) {

        const sortedFlavors = Object.entries(flavors).sort((a,b) => b[1] - a[1]);

        if (sortedFlavors.length === 0) {

            flavorsContainer.innerHTML = '<div class="text-xs text-gray-400 col-span-2 py-2">কোনো পণ্যের তথ্য পাওয়া যায়নি।</div>';

        } else {

            flavorsContainer.innerHTML = sortedFlavors.map(([name, qty]) => `

                <div class="flex items-center justify-between p-2.5 rounded-xl bg-white border border-gray-200/90 shadow-2xs">

                    <span class="text-xs font-extrabold text-gray-800 truncate pr-2">🥒 ${name}</span>

                    <span class="bg-amber-400 text-slate-950 font-black text-xs px-2.5 py-0.5 rounded-lg shrink-0">${qty} Jar${qty > 1 ? 's' : ''}</span>

                </div>

            `).join('');

        }

    }



    // Render Orders Checklist

    const ordersContainer = document.getElementById('bulkPackingOrdersList');

    if (ordersContainer) {

        ordersContainer.innerHTML = orders.map((o, idx) => `

            <div class="p-3 bg-white flex items-start gap-3 hover:bg-amber-50/20 transition">

                <input type="checkbox" id="pack_check_${idx}" class="mt-1 w-4 h-4 rounded text-emerald-600 focus:ring-emerald-500 border-gray-300 cursor-pointer">

                <label for="pack_check_${idx}" class="flex-1 cursor-pointer min-w-0 select-none">

                    <div class="flex items-center justify-between gap-2 flex-wrap">

                        <span class="font-display font-black text-xs text-brand-900">#${o.orderNumber} • ${o.customerName}</span>

                        <span class="text-[11px] font-bold text-amber-800 bg-amber-50 border border-amber-200 px-2 py-0.2 rounded-md">${o.jarCount} Jars (৳${o.amount.toFixed(0)})</span>

                    </div>

                    <div class="text-[11px] text-gray-500 truncate mt-0.5">${o.phone}${o.city ? ' • ' + o.city : ''}</div>

                    <div class="mt-1.5 flex flex-wrap gap-1">

                        ${o.items.length > 0 ? o.items.map(it => `<span class="inline-flex items-center text-[10px] font-bold bg-gray-100 text-gray-800 px-2 py-0.5 rounded-md border border-gray-200">${it.qty}x ${it.name}</span>`).join('') : '<span class="text-[10px] text-gray-400">Items not listed</span>'}

                    </div>

                </label>

            </div>

        `).join('');

    }



    document.getElementById('bulkPackingModal').classList.remove('hidden');

}



function closeBulkPackingModal() {

    const modal = document.getElementById('bulkPackingModal');

    if (modal) modal.classList.add('hidden');

}



function copyBulkPackingSummary() {

    if (!currentPackingData || currentPackingData.orders.length === 0) return;

    

    let text = `📦 PICKPICKLES KITCHEN PACKING LIST\n`;

    text += `━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n`;

    text += `Total Orders: ${currentPackingData.orders.length} | Total Jars: ${currentPackingData.totalJars}\n\n`;

    text += `🏺 REQUIRED JARS BREAKDOWN:\n`;

    for (const [flavor, qty] of Object.entries(currentPackingData.flavors)) {

        text += `• ${flavor}: ${qty} jars\n`;

    }

    text += `\n📋 ORDER DETAILS:\n`;

    currentPackingData.orders.forEach(o => {

        text += `\n[ ] #${o.orderNumber} - ${o.customerName} (${o.phone}${o.city ? ', ' + o.city : ''})\n`;

        o.items.forEach(it => {

            text += `    - ${it.qty}x ${it.name}\n`;

        });

    });



    navigator.clipboard.writeText(text).then(() => {

        const btnTxt = document.getElementById('copyPackingBtnTxt');

        if (btnTxt) {

            btnTxt.innerText = 'কপি হয়েছে! (Copied)';

            setTimeout(() => { btnTxt.innerText = 'কপি করুন (Copy Text)'; }, 2000);

        }

    }).catch(err => {

        alert('কপিতে ত্রুটি: ' + err);

    });

}



function printBulkPackingSlip() {

    if (!currentPackingData || currentPackingData.orders.length === 0) return;

    

    const printWindow = window.open('', '_blank');

    const flavorsHtml = Object.entries(currentPackingData.flavors).map(([f, q]) => `

        <tr style="border-bottom: 1px solid #e2e8f0;">

            <td style="padding: 8px 12px; font-weight: bold;">🥒 ${f}</td>

            <td style="padding: 8px 12px; text-align: right; font-weight: 900; font-size: 16px; color: #047857;">${q}</td>

        </tr>

    `).join('');



    const ordersHtml = currentPackingData.orders.map(o => `

        <div style="border: 1px solid #cbd5e1; border-radius: 8px; padding: 10px; margin-bottom: 10px; page-break-inside: avoid;">

            <div style="display: flex; justify-content: space-between; font-weight: bold; font-size: 14px; border-bottom: 1px solid #f1f5f9; padding-bottom: 4px;">

                <span>[  ] #${o.orderNumber} — ${o.customerName} (${o.phone})</span>

                <span>${o.jarCount} Jars • ৳${o.amount.toFixed(0)}</span>

            </div>

            <div style="font-size: 12px; color: #64748b; margin-top: 4px;">${o.address ? o.address + ', ' : ''}${o.city}</div>

            <div style="margin-top: 6px; font-size: 13px; font-weight: 600;">

                ${o.items.map(it => `<span style="display: inline-block; background: #f1f5f9; padding: 2px 8px; border-radius: 4px; margin-right: 6px; border: 1px solid #e2e8f0;">${it.qty}x ${it.name}</span>`).join('')}

            </div>

        </div>

    `).join('');



    let flavorsRows = '';

    for (const [flavor, qty] of Object.entries(currentPackingData.flavors)) {

        flavorsRows += '<tr style="border-bottom: 1px solid #e2e8f0;">' +

            '<td style="padding: 8px 12px; font-weight: bold;">🥒 ' + flavor + '</td>' +

            '<td style="padding: 8px 12px; text-align: right; font-weight: 900; font-size: 16px; color: #047857;">' + qty + '</td>' +

            '</tr>';

    }



    let ordersCards = '';

    currentPackingData.orders.forEach(o => {

        let itemsBadges = '';

        o.items.forEach(it => {

            itemsBadges += '<span style="display: inline-block; background: #f1f5f9; padding: 2px 8px; border-radius: 4px; margin-right: 6px; border: 1px solid #e2e8f0; font-size: 11px;">' + it.qty + 'x ' + it.name + '</span>';

        });

        ordersCards += '<div style="border: 1px solid #cbd5e1; border-radius: 8px; padding: 10px; margin-bottom: 10px; page-break-inside: avoid;">' +

            '<div style="display: flex; justify-content: space-between; font-weight: bold; font-size: 13px; border-bottom: 1px solid #f1f5f9; padding-bottom: 4px;">' +

            '<span>[  ] #' + o.orderNumber + ' — ' + o.customerName + ' (' + o.phone + ')</span>' +

            '<span>' + o.jarCount + ' Jars • ৳' + o.amount.toFixed(0) + '</span>' +

            '</div>' +

            '<div style="font-size: 11px; color: #64748b; margin-top: 4px;">' + (o.address ? o.address + ', ' : '') + o.city + '</div>' +

            '<div style="margin-top: 6px;">' + itemsBadges + '</div>' +

            '</div>';

    });



    const fullHtml = '<!DOCTYPE html><html><head><title>Kitchen Packing Slip - Pickpickles</title>' +

        '<style>body { font-family: system-ui, -apple-system, sans-serif; padding: 20px; color: #0f172a; max-width: 800px; margin: auto; } @media print { body { padding: 0; } }</style>' +

        '</head><body>' +

        '<div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #0f172a; padding-bottom: 10px; margin-bottom: 15px;">' +

        '<div><h1 style="margin: 0; font-size: 20px;">🥒 Pickpickles — Kitchen Packing Slip</h1><p style="margin: 3px 0 0; font-size: 11px; color: #64748b;">Printed at ' + (new Date().toLocaleString()) + '</p></div>' +

        '<div style="text-align: right;"><div style="font-size: 18px; font-weight: 900; color: #047857;">Total: ' + currentPackingData.totalJars + ' Jars</div><div style="font-size: 11px; color: #64748b;">' + currentPackingData.orders.length + ' Orders Selected</div></div>' +

        '</div>' +

        '<h3 style="margin: 15px 0 8px; font-size: 14px; text-transform: uppercase;">1. Flavors Required from Kitchen</h3>' +

        '<table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">' +

        '<thead><tr style="background: #f8fafc; border-bottom: 2px solid #cbd5e1; text-align: left; font-size: 12px;"><th style="padding: 6px 12px;">Flavor Name</th><th style="padding: 6px 12px; text-align: right;">Total Quantity</th></tr></thead>' +

        '<tbody>' + flavorsRows + '</tbody></table>' +

        '<h3 style="margin: 15px 0 8px; font-size: 14px; text-transform: uppercase;">2. Order Packing Checklist</h3>' +

        ordersCards +

        '<' + 'script>window.onload = function() { window.print(); };<' + '/script>' +

        '</body></html>';



    printWindow.document.write(fullHtml);

    printWindow.document.close();

}



function openBulkWhatsAppModal() {

    const checkedBoxes = getUniqueSelectedOrderCheckboxes();

    if (checkedBoxes.length === 0) {

        alert('Please select at least one order to send WhatsApp message.');

        return;

    }



    bulkSelectedOrdersQueue = checkedBoxes.map(cb => ({

        orderNumber: cb.dataset.orderNumber,

        customerName: cb.dataset.customerName || 'Customer',

        phone: cb.dataset.phone || '',

        status: cb.dataset.status,

        waUrl: cb.dataset.waUrl || '',

        sent: false

    })).filter(item => item.phone && item.waUrl);



    if (bulkSelectedOrdersQueue.length === 0) {

        alert('None of the selected orders have a valid phone number or WhatsApp message link.');

        return;

    }



    renderBulkWaQueue();

    updateBulkWaRunner();

    document.getElementById('bulkWhatsAppModal').classList.remove('hidden');

}



function closeBulkWhatsAppModal() {

    document.getElementById('bulkWhatsAppModal').classList.add('hidden');

}



function renderBulkWaQueue() {

    const container = document.getElementById('bulkWaQueueList');

    if (!container) return;

    

    let html = '';

    bulkSelectedOrdersQueue.forEach((item, index) => {

        html += `

        <div class="p-3 flex items-center justify-between gap-3 hover:bg-gray-50 transition ${item.sent ? 'bg-emerald-50/40' : ''}" id="bulk_wa_row_${index}">

            <div class="flex items-center gap-2.5 min-w-0">

                <span class="w-6 h-6 rounded-full ${item.sent ? 'bg-emerald-600 text-white' : 'bg-gray-100 text-gray-700'} font-bold text-[11px] flex items-center justify-center shrink-0">

                    ${item.sent ? '<i class="fa-solid fa-check"></i>' : (index + 1)}

                </span>

                <div class="min-w-0">

                    <div class="flex items-center gap-1.5 flex-wrap">

                        <strong class="text-xs text-gray-900 truncate">${item.customerName}</strong>

                        <span class="text-[10px] font-mono font-bold text-brand-700">#${item.orderNumber}</span>

                    </div>

                    <div class="text-[11px] text-gray-500 font-mono">

                        ${item.phone}

                    </div>

                </div>

            </div>



            <div class="flex items-center gap-2 shrink-0">

                ${item.sent ? `

                    <span class="text-[10px] font-black text-emerald-800 bg-emerald-100 px-2 py-0.5 rounded border border-emerald-300">

                        <i class="fa-solid fa-circle-check"></i> Sent

                    </span>

                ` : ''}

                <button 

                    type="button" 

                    onclick="triggerSingleWaSend(${index})"

                    class="bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold px-3 py-1.5 rounded-xl shadow-2xs transition inline-flex items-center gap-1 cursor-pointer active:scale-95"

                    title="Open WhatsApp chat for this customer"

                >

                    <i class="fa-brands fa-whatsapp text-sm"></i>

                    <span>${item.sent ? 'Resend' : 'Send'}</span>

                </button>

            </div>

        </div>`;

    });



    container.innerHTML = html;

}



function updateBulkWaRunner() {

    const total = bulkSelectedOrdersQueue.length;

    const sentCount = bulkSelectedOrdersQueue.filter(i => i.sent).length;

    

    const progressSpan = document.getElementById('bulkWaProgressTxt');

    if (progressSpan) {

        progressSpan.textContent = `${sentCount} / ${total} Sent`;

    }



    const nextUnsentIndex = bulkSelectedOrdersQueue.findIndex(i => !i.sent);

    const targetName = document.getElementById('bulkWaCurrentTargetName');

    const targetPhone = document.getElementById('bulkWaCurrentTargetPhone');

    const nextBtn = document.getElementById('bulkWaNextBtn');



    if (nextUnsentIndex !== -1) {

        const nextCustomer = bulkSelectedOrdersQueue[nextUnsentIndex];

        if (targetName) targetName.textContent = nextCustomer.customerName + ' (#' + nextCustomer.orderNumber + ')';

        if (targetPhone) targetPhone.textContent = '• ' + nextCustomer.phone;

        if (nextBtn) {

            nextBtn.disabled = false;

            nextBtn.className = "bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-black px-4 py-2 rounded-xl shadow-md transition inline-flex items-center gap-2 cursor-pointer active:scale-95";

            nextBtn.innerHTML = '<i class="fa-brands fa-whatsapp text-sm"></i> <span>Send & Next ➔</span>';

        }

    } else {

        if (targetName) targetName.textContent = 'All messages sent! 🎉';

        if (targetPhone) targetPhone.textContent = '';

        if (nextBtn) {

            nextBtn.disabled = true;

            nextBtn.className = "bg-gray-300 text-gray-600 text-xs font-black px-4 py-2 rounded-xl shadow-2xs inline-flex items-center gap-2 cursor-not-allowed";

            nextBtn.innerHTML = '<i class="fa-solid fa-circle-check text-emerald-600"></i> <span>Completed</span>';

        }

    }

}



function triggerSingleWaSend(index) {

    if (!bulkSelectedOrdersQueue[index]) return;

    const customer = bulkSelectedOrdersQueue[index];

    window.open(customer.waUrl, '_blank');

    customer.sent = true;

    renderBulkWaQueue();

    updateBulkWaRunner();

}



function sendNextWhatsAppInQueue() {

    const nextUnsentIndex = bulkSelectedOrdersQueue.findIndex(i => !i.sent);

    if (nextUnsentIndex !== -1) {

        triggerSingleWaSend(nextUnsentIndex);

    }

}



function openAllWhatsAppBatch() {

    const unsentList = bulkSelectedOrdersQueue.filter(i => !i.sent);

    if (unsentList.length === 0) {

        alert('All selected customers have already been sent.');

        return;

    }



    if (!confirm(`Open WhatsApp in browser for ${unsentList.length} customer(s)? (Note: please allow popups if prompted)`)) {

        return;

    }



    unsentList.forEach((customer, idx) => {

        setTimeout(() => {

            window.open(customer.waUrl, '_blank');

            customer.sent = true;

            renderBulkWaQueue();

            updateBulkWaRunner();

        }, idx * 400);

    });

}



function copyAllSelectedPhones() {

    const phones = bulkSelectedOrdersQueue.map(i => i.phone).filter(Boolean);

    if (phones.length === 0) return;

    const text = phones.join(', ');

    navigator.clipboard.writeText(text).then(() => {

        alert(`Copied ${phones.length} phone numbers to clipboard!`);

    }).catch(() => {

        prompt('Copy phone numbers:', text);

    });

}

