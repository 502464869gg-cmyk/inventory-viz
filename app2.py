import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import datetime
import json
import os
import math

# ================= 0. 访问权限拦截 =================
password = st.sidebar.text_input("🔒 请输入内部授权码", type="password")
if password != "hmdz888":  # 这里的 888888 可以换成你想要的任何密码
    st.warning("✋ 这是内部备货推演沙盘，请输入正确的授权码后方可使用。")
    st.stop()  # 密码不对，直接停止运行后面的所有代码



# ================= 1. 核心业务逻辑与本地数据库 =================
DEFAULT_ASIN = "BFN-143"
DEFAULT_STOCK = 600
CONFIG_FILE = "asin_settings.json"
GLOBAL_LOGISTICS_FILE = "global_logistics.json"
MOQ_UNITS = 500  # 全局起批线
FAST_SEA_THRESHOLD = 35 # 海运快慢船硬性界定线(天)

DEFAULT_LOGISTICS = {
    "HQYD-红单包税": 9, "HQYD-空加派(带电)": 18, "HQYD-空加派(普货)": 18,
    "HQYD-海运快线-限时达": 30, "HQYD-海运快线-限时达(卡派)": 32, "HQYD-海运-合德": 35,
    "HQYD-海运-合德(卡派)": 35, "HQYD-海运慢线": 45, "HQYD-海运海卡": 55,
    "HQYD-加拿大红单包税": 9, "HQYD-加拿大空加派包税": 18, "HQYD-加拿大海运包税": 40,
    "HQYD-加拿大海运限时达包税": 33, "HQYD-加拿大海卡包税(卡派)": 55,
    "HQYD-德国卡航自主VAT": 35, "HQYD-德国海快自主VAT": 65,
    "HQYD-英国卡航自主VAT": 35, "HQYD-英国海快自主VAT": 60
}

CH_CLASSIFICATION = {
    "US": {
        "AIR": ["HQYD-红单包税", "HQYD-空加派(带电)", "HQYD-空加派(普货)"],
        "SEA": ["HQYD-海运快线-限时达", "HQYD-海运快线-限时达(卡派)", "HQYD-海运-合德", "HQYD-海运-合德(卡派)", "HQYD-海运慢线", "HQYD-海运海卡"]
    },
    "CA": {
        "AIR": ["HQYD-加拿大红单包税", "HQYD-加拿大空加派包税"],
        "SEA": ["HQYD-加拿大海运包税", "HQYD-加拿大海运限时达包税", "HQYD-加拿大海卡包税(卡派)"]
    }
}

def get_beijing_today():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).date()

def load_all_configs():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}
    return {}

def save_config(asin, data=None, delete=False, new_name=None):
    configs = load_all_configs()
    if delete and asin in configs: del configs[asin]
    elif new_name and asin in configs: configs[new_name] = configs.pop(asin)
    elif data: configs[asin] = data
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(configs, f, ensure_ascii=False, indent=4)

def load_logistics():
    if os.path.exists(GLOBAL_LOGISTICS_FILE):
        try:
            with open(GLOBAL_LOGISTICS_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
    return DEFAULT_LOGISTICS.copy()

def save_logistics(data):
    with open(GLOBAL_LOGISTICS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

LOGISTICS_CHANNELS = load_logistics()
ch_list = list(LOGISTICS_CHANNELS.keys())

def create_callbacks(d_key, b_key, s_key):
    def sync_forward(): st.session_state[s_key] = st.session_state[d_key] + datetime.timedelta(days=st.session_state[b_key])
    def sync_backward():
        delta = (st.session_state[s_key] - st.session_state[d_key]).days
        if delta < 0:
            st.session_state[s_key] = st.session_state[d_key]
            st.session_state[b_key] = 0
        else: st.session_state[b_key] = delta
    return sync_forward, sync_backward

def get_best_channel(t_15_max_days, t_0_max_days, tolerance_days, region_code):
    seas = {k: v for k, v in LOGISTICS_CHANNELS.items() if k in CH_CLASSIFICATION[region_code]["SEA"]}
    airs = {k: v for k, v in LOGISTICS_CHANNELS.items() if k in CH_CLASSIFICATION[region_code]["AIR"]}
    if not seas: seas = LOGISTICS_CHANNELS
    if not airs: airs = LOGISTICS_CHANNELS
    
    p1_seas = {k: v for k, v in seas.items() if v <= t_15_max_days}
    if p1_seas: return max(p1_seas, key=p1_seas.get), False, "P1"

    p2_seas = {k: v for k, v in seas.items() if v <= t_0_max_days}
    if p2_seas: return max(p2_seas, key=p2_seas.get), False, "P2"

    p3_seas = {k: v for k, v in seas.items() if v <= t_0_max_days + tolerance_days}
    if p3_seas: return min(p3_seas, key=p3_seas.get), False, "P3"

    p4_airs = {k: v for k, v in airs.items() if v <= t_0_max_days + tolerance_days}
    if p4_airs: return min(p4_airs, key=p4_airs.get), True, "P4"

    return min(LOGISTICS_CHANNELS, key=LOGISTICS_CHANNELS.get), True, "Crisis"

# ================= 2. 页面基础渲染 & ASIN 档案中枢 =================
st.set_page_config(page_title="全景备货推演沙盘 V8.1", layout="wide")
st.title("📦 亚马逊【全链路物流】精算沙盘 (V8.1 边界对齐版)")
st.markdown("已升级：阶段日期精准闭环 | 智能双轨拦截 | 极简相对坐标组件")

if "asin_input" not in st.session_state: st.session_state.asin_input = DEFAULT_ASIN
all_configs = load_all_configs()

col_top1, col_top2 = st.columns([8, 2])
with col_top1:
    if all_configs:
        st.markdown("📌 **历史档案直达：**")
        asin_keys = list(all_configs.keys())
        buttons_per_row = 8
        for i in range(0, len(asin_keys), buttons_per_row):
            batch_keys = asin_keys[i:i+buttons_per_row]
            cols = st.columns(buttons_per_row)
            for idx, saved_asin in enumerate(batch_keys):
                btn_style = "primary" if saved_asin == st.session_state.asin_input else "secondary"
                if cols[idx].button(f"🏷️ {saved_asin}", key=f"q_{saved_asin}", type=btn_style, use_container_width=True):
                    st.session_state.asin_input = saved_asin
                    st.rerun()

st.divider()

col_b1, col_b2, col_b3, col_b4 = st.columns([2.5, 2.5, 2, 3])
asin_name = col_b1.text_input("当前推演 ASIN", key="asin_input")
c_data = all_configs.get(asin_name, {})

# --- 核心状态与 Callback 提前定义 ---
view_mode_key = f"view_mode_{asin_name}"
if view_mode_key not in st.session_state:
    st.session_state[view_mode_key] = c_data.get("view_mode", "展开节点详情 (错落防撞)")
    
y_offset_key = f"y_offset_{asin_name}"
if y_offset_key not in st.session_state:
    st.session_state[y_offset_key] = int(c_data.get("y_offset", 65))

def save_view_settings():
    configs = load_all_configs()
    if asin_name in configs:
        configs[asin_name]["view_mode"] = st.session_state[view_mode_key]
        configs[asin_name]["y_offset"] = st.session_state[y_offset_key]
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(configs, f, ensure_ascii=False, indent=4)

def toggle_view_mode():
    configs = load_all_configs()
    if asin_name in configs:
        configs[asin_name]["view_mode"] = st.session_state[view_mode_key]
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(configs, f, ensure_ascii=False, indent=4)

def apply_ai_plan(plan_list, lead):
    if not plan_list: return
    required_slots = len(plan_list)
    st.session_state[f"n_count_{asin_name}"] = max(5, required_slots)
    current_date = st.session_state[f"start_date_{asin_name}"]
    
    for idx, (ch, qty) in enumerate(plan_list):
        st.session_state[f"n_ch_{idx}_{asin_name}"] = ch
        st.session_state[f"n_qty_{idx}_{asin_name}"] = qty
        st.session_state[f"n_lead_{idx}_{asin_name}"] = lead
        st.session_state[f"n_anchor_{idx}_{asin_name}"] = current_date
        st.session_state[f"n_orig_lead_{idx}_{asin_name}"] = lead
        
    for idx in range(len(plan_list), st.session_state[f"n_count_{asin_name}"]):
        st.session_state[f"n_qty_{idx}_{asin_name}"] = 0

start_date_key = f"start_date_{asin_name}"
prev_date_key = f"prev_start_date_{asin_name}"
stock_key = f"initial_stock_{asin_name}"

if start_date_key not in st.session_state:
    init_start = get_beijing_today()
    if "start_date" in c_data:
        try: init_start = datetime.datetime.strptime(c_data["start_date"], '%Y-%m-%d').date()
        except: pass
    st.session_state[start_date_key] = init_start

if prev_date_key not in st.session_state:
    st.session_state[prev_date_key] = st.session_state[start_date_key]

def handle_date_shift(a_name, config):
    s_key = f"start_date_{a_name}"
    p_key = f"prev_start_date_{a_name}"
    stk_key = f"initial_stock_{a_name}"

    new_date = st.session_state[s_key]
    prev_date = st.session_state.get(p_key, new_date)

    if new_date != prev_date:
        delta_days = (new_date - prev_date).days
        global_s = int(config.get("global_sales", 10))
        phases = config.get("phases", [])

        if delta_days > 0:
            calc_start = prev_date
            days_to_calc = delta_days
            sign = -1 
        else:
            calc_start = new_date
            days_to_calc = abs(delta_days)
            sign = 1  

        current_phase_start = calc_start
        daily_sales = []
        for p in phases:
            end_str = p.get("end_date")
            if end_str:
                try: p_end = datetime.datetime.strptime(end_str, '%Y-%m-%d').date()
                except: p_end = current_phase_start + datetime.timedelta(days=29)
            else:
                p_end = current_phase_start + datetime.timedelta(days=p.get("days", 30)-1)
            
            p_days = (p_end - current_phase_start).days + 1
            if p_days > 0:
                daily_sales.extend([int(p.get("sales", global_s))] * p_days)
                current_phase_start = p_end + datetime.timedelta(days=1)
        
        daily_sales.extend([global_s] * (days_to_calc + 30))
        sales_in_period = sum(daily_sales[:days_to_calc])

        old_stock = st.session_state.get(stk_key, int(config.get("initial_stock", DEFAULT_STOCK)))
        new_stock = old_stock + (sign * sales_in_period)
        st.session_state[stk_key] = max(0, new_stock) 

        n_count = st.session_state.get(f"n_count_{a_name}", max(5, len(config.get("new", []))))
        for i in range(n_count):
            lead_k = f"n_lead_{i}_{a_name}"
            anchor_k = f"n_anchor_{i}_{a_name}"
            orig_lead_k = f"n_orig_lead_{i}_{a_name}"
            if anchor_k in st.session_state and orig_lead_k in st.session_state:
                expected_ship = st.session_state[anchor_k] + datetime.timedelta(days=st.session_state[orig_lead_k])
                new_dynamic_lead = max(0, (expected_ship - new_date).days)
                st.session_state[lead_k] = new_dynamic_lead

        st.session_state[p_key] = new_date

def sync_today_action(a_name, config):
    st.session_state[f"start_date_{a_name}"] = get_beijing_today()
    handle_date_shift(a_name, config)

initial_stock = col_b2.number_input("可用库存", min_value=0, value=int(c_data.get("initial_stock", DEFAULT_STOCK)), key=stock_key)
box_qty = col_b3.number_input("📦 单箱数", min_value=1, value=int(c_data.get("box_qty", 7)), key=f"box_qty_{asin_name}")

with col_b4:
    c_b4_1, c_b4_2 = st.columns([6, 4])
    start_date = c_b4_1.date_input("📅 推演起始日", key=start_date_key, on_change=handle_date_shift, args=(asin_name, c_data))
    st.markdown("""<style>div[data-testid="column"]:nth-of-type(4) div[data-testid="stButton"] {margin-top: 28px;}</style>""", unsafe_allow_html=True)
    c_b4_2.button("🔄 同步今日", on_click=sync_today_action, args=(asin_name, c_data))

with st.expander("⚙️ 高级档案管理 (重命名 / 永久删除 / 存档)", expanded=False):
    m_col1, m_col2, m_col3 = st.columns(3)
    new_asin_name = m_col1.text_input("重命名当前档案", value=asin_name)
    if m_col2.button("📝 确认重命名", use_container_width=True):
        if new_asin_name and new_asin_name != asin_name and asin_name in all_configs:
            save_config(asin_name, new_name=new_asin_name)
            st.session_state.asin_input = new_asin_name
            st.success("重命名成功！")
            st.rerun()
    if m_col3.button("🗑️ 永久删除当前档案", type="primary", use_container_width=True):
        if asin_name in all_configs:
            save_config(asin_name, delete=True)
            st.session_state.asin_input = DEFAULT_ASIN
            st.warning(f"档案 {asin_name} 已彻底删除！")
            st.rerun()
    if st.button("💾 手动覆盖存档当前参数", type="primary", use_container_width=True):
        st.session_state["trigger_save"] = True 

# ================= 3. 侧边栏：全局变量与动态日历 =================
st.sidebar.header("🌍 全局物流时效配置")
with st.sidebar.expander("⚙️ 编辑物流渠道时效 (双击修改)", expanded=False):
    df_log = pd.DataFrame(list(LOGISTICS_CHANNELS.items()), columns=["渠道名称", "时效(天)"])
    edited_df = st.data_editor(df_log, num_rows="dynamic", use_container_width=True, hide_index=True)
    if st.button("💾 保存物流全局配置", use_container_width=True):
        new_log = dict(zip(edited_df["渠道名称"], edited_df["时效(天)"]))
        save_logistics(new_log)
        st.success("全局物流更新成功！")
        st.rerun()

st.sidebar.divider()
st.sidebar.header("⚙️ 资金流与安全控制")
col_c1, col_c2 = st.sidebar.columns(2)
fba_delay = col_c1.number_input("⏳ FBA 上架延迟(天)", min_value=0, value=int(c_data.get("fba_delay", 5)), key=f"fba_delay_{asin_name}")
tolerance_days = col_c2.number_input("🛡️ 容忍断货(天)", min_value=0, value=int(c_data.get("tolerance_days", 7)), key=f"tol_{asin_name}")
cover_days = st.sidebar.number_input("🎯 目标补货周期(天)", min_value=1, value=int(c_data.get("cover_days", 30)), key=f"cover_{asin_name}")

st.sidebar.markdown("#### ⚖️ 快慢船资金统筹策略")
slicing_strategy = st.sidebar.radio("✂️ 切分算法选择：", 
                                    ["按全局总盘子切分 (优先老货走快船)", "按单批次独立切分 (雨露均沾)"], 
                                    index=0 if c_data.get("slicing_strategy", "全局") == "全局" else 1,
                                    key=f"slice_{asin_name}")
fast_pct = st.sidebar.slider("🚀 快速份额目标占比 (%)", min_value=0, max_value=100, value=int(c_data.get("fast_pct", 40)), step=5, key=f"fast_pct_{asin_name}")

st.sidebar.header("📈 需求侧：促销日历")
phase_count_key = f"phase_count_{asin_name}"
saved_phases = c_data.get("phases", [{"name": "常规平销期", "end_date": (start_date + datetime.timedelta(days=29)).strftime('%Y-%m-%d'), "sales": 10}])
if phase_count_key not in st.session_state: st.session_state[phase_count_key] = max(1, len(saved_phases))
col_s1, col_s2 = st.sidebar.columns([6, 4])
global_sales = col_s1.number_input("🌎 默认日常销(单/天)", min_value=0, value=int(c_data.get("global_sales", 10)), key=f"global_sales_{asin_name}")
if col_s2.button("🔄 同步销量", use_container_width=True):
    for i in range(st.session_state[phase_count_key]): st.session_state[f"p_sales_{i}_{asin_name}"] = global_sales
    st.sidebar.success("已同步")

phases = []
current_phase_start = start_date

for i in range(st.session_state[phase_count_key]):
    saved_p = saved_phases[i] if i < len(saved_phases) else {}
    saved_end_str = saved_p.get("end_date")
    if saved_end_str:
        try: default_end_date = datetime.datetime.strptime(saved_end_str, '%Y-%m-%d').date()
        except: default_end_date = current_phase_start + datetime.timedelta(days=29)
    else:
        fallback_days = saved_p.get("days", 30)
        default_end_date = current_phase_start + datetime.timedelta(days=fallback_days - 1)
        
    with st.sidebar.expander(f"⚙️ 第 {i+1} 阶段设置", expanded=(i<2)):
        p_name = st.text_input(f"阶段 {i+1} 名称", value=saved_p.get("name", f"阶段{i+1}"), key=f"p_name_{i}_{asin_name}")
        p_end = st.date_input(f"[{p_name}] 结束日期 (固定锚点)", value=default_end_date, key=f"p_end_{i}_{asin_name}")
        p_days = (p_end - current_phase_start).days + 1
        p_sales_key = f"p_sales_{i}_{asin_name}"
        if p_sales_key not in st.session_state: st.session_state[p_sales_key] = int(saved_p.get("sales", global_sales))
        p_sales = st.slider(f"[{p_name}] 日均销预估", min_value=0, max_value=500, key=p_sales_key)
        
        if p_days > 0:
            phases.append({"name": p_name, "start": current_phase_start, "end": p_end, "days": p_days, "sales": p_sales})
            current_phase_start = p_end + datetime.timedelta(days=1)
        else:
            st.warning(f"⚠️ 结束日 ({p_end.strftime('%m-%d')}) 在当前起始日之前，本阶段已被自动折叠跳过。")

daily_sales_array = []
for p in phases: daily_sales_array.extend([p["sales"]] * p["days"])
daily_sales_array.extend([global_sales] * 400) 

c1_ph, c2_ph = st.sidebar.columns(2)
if c1_ph.button("➕ 新增阶段", use_container_width=True, key=f"add_ph_{asin_name}"): st.session_state[phase_count_key] += 1; st.rerun()
if c2_ph.button("➖ 删除阶段", use_container_width=True, key=f"del_ph_{asin_name}"):
    if st.session_state[phase_count_key] > 1: st.session_state[phase_count_key] -= 1; st.rerun()

# ================= 4. 供给侧前置录入 =================
baseline_batches = [] 
prod_batches_raw = [] 
user_new_batches = [] 

st.sidebar.header("🚚 供给侧：进度监控")

saved_fc = c_data.get("fc", {"qty": 0, "days": 7})
st.sidebar.subheader("0. 🔄 FC 内部调拨")
with st.sidebar.expander("展开设置预留库存", expanded=False):
    fc_qty = st.number_input("预留库总量", min_value=0, value=int(saved_fc["qty"]), step=50, key=f"fc_qty_{asin_name}")
    fc_days = st.number_input("处理时效", min_value=1, value=int(saved_fc["days"]), key=f"fc_days_{asin_name}")
    if fc_qty > 0:
        daily_fc, remainder = fc_qty // fc_days, fc_qty % fc_days
        for d in range(1, fc_days + 1):
            release_today = daily_fc + (1 if d <= remainder else 0)
            if release_today > 0: baseline_batches.append({"name": "FC滴灌", "qty": release_today, "day": d, "hide_label": True})

saved_transit_list = c_data.get("transit_list", [{"ch": "HQYD-海运快线-限时达", "ship_date": start_date.strftime('%Y-%m-%d'), "qty": 0}] * 8)
t_count_key = f"t_count_{asin_name}"
if t_count_key not in st.session_state: st.session_state[t_count_key] = max(8, len(saved_transit_list))

st.sidebar.subheader(f"1. 🚢 已发货在途 ({st.session_state[t_count_key]}槽)")
col_t_g1, col_t_g2 = st.sidebar.columns([6, 4])
with col_t_g1:
    global_t_date = st.date_input("🌍 全局实际发货日", value=start_date, key=f"g_t_date_{asin_name}")

def sync_transit_dates(a_name, target_date):
    t_cnt = st.session_state.get(f"t_count_{a_name}", 8)
    for idx in range(t_cnt):
        st.session_state[f"t_date_{idx}_{a_name}"] = target_date

with col_t_g2:
    st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
    st.button("🔄 同步发货日", use_container_width=True, on_click=sync_transit_dates, args=(asin_name, global_t_date), key=f"sync_t_{asin_name}")

transit_state = []
for i in range(st.session_state[t_count_key]):
    if i >= len(saved_transit_list): saved_transit_list.append({"ch": "HQYD-海运快线-限时达", "ship_date": start_date.strftime('%Y-%m-%d'), "qty": 0})
    try: saved_t_date = datetime.datetime.strptime(saved_transit_list[i].get("ship_date", start_date.strftime('%Y-%m-%d')), '%Y-%m-%d').date()
    except: saved_t_date = start_date
    t_ch_saved = saved_transit_list[i].get("ch", "HQYD-海运快线-限时达")
    t_index = ch_list.index(t_ch_saved) if t_ch_saved in ch_list else 3
    t_qty_saved = int(saved_transit_list[i].get("qty", 0))

    with st.sidebar.expander(f"在途货件 {i+1}", expanded=(i==0 or t_qty_saved > 0)):
        t_ch = st.selectbox(f"发运渠道 {i+1}", ch_list, index=t_index, key=f"t_ch_{i}_{asin_name}")
        t_date = st.date_input(f"实际发货日 {i+1}", value=saved_t_date, key=f"t_date_{i}_{asin_name}")
        t_qty = st.number_input(f"发货数量 {i+1}", min_value=0, value=t_qty_saved, step=50, key=f"t_qty_{i}_{asin_name}")
        
        if t_qty > 0 and t_qty % box_qty != 0:
            lower, upper = t_qty - (t_qty % box_qty), t_qty + (box_qty - (t_qty % box_qty))
            st.warning(f"⚠️ `{t_qty}件` 非整箱！建议: **`{lower}件`** 或 **`{upper}件`**")
            
        transit_state.append({"ch": t_ch, "ship_date": t_date.strftime('%Y-%m-%d'), "qty": t_qty})
        if t_qty > 0:
            arr_date = t_date + datetime.timedelta(days=LOGISTICS_CHANNELS[t_ch] + fba_delay)
            days_to_arr = (arr_date - start_date).days
            if days_to_arr > 0: baseline_batches.append({"name": f"在途{i+1}:{t_ch.split('-')[-1]}", "qty": t_qty, "day": days_to_arr})

c1_t, c2_t = st.sidebar.columns(2)
if c1_t.button("➕ 增在途槽", use_container_width=True, key=f"add_t_{asin_name}"): st.session_state[t_count_key] += 1; st.rerun()
if c2_t.button("➖ 删在途槽", use_container_width=True, key=f"del_t_{asin_name}"):
    if st.session_state[t_count_key] > 1: st.session_state[t_count_key] -= 1; st.rerun()

saved_prod = c_data.get("prod", [{"ch": "HQYD-海运快线-限时达", "qty": 0}] * 5)
p_count_key = f"p_count_{asin_name}"
if p_count_key not in st.session_state: st.session_state[p_count_key] = max(5, len(saved_prod))

st.sidebar.subheader(f"2. 🏭 采购中弹药库 ({st.session_state[p_count_key]}槽)")
col_p_g1, col_p_g2 = st.sidebar.columns([6, 4])
with col_p_g1:
    global_p_deliv = st.date_input("🌍 全局预计交货日", value=start_date + datetime.timedelta(days=15), key=f"g_p_deliv_{asin_name}")

def sync_prod_dates(a_name, target_date):
    p_cnt = st.session_state.get(f"p_count_{a_name}", 5)
    for idx in range(p_cnt):
        d_key = f"p_deliv_{idx}_{a_name}"
        b_key = f"p_buf_{idx}_{a_name}"
        s_key = f"p_ship_{idx}_{a_name}"
        st.session_state[d_key] = target_date
        buf_val = st.session_state.get(b_key, 1)
        st.session_state[s_key] = target_date + datetime.timedelta(days=buf_val)

with col_p_g2:
    st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
    st.button("🔄 同步交货日", use_container_width=True, on_click=sync_prod_dates, args=(asin_name, global_p_deliv), key=f"sync_p_{asin_name}")

prod_state = []
for i in range(st.session_state[p_count_key]):
    if i >= len(saved_prod): saved_prod.append({"ch": "HQYD-海运快线-限时达", "qty": 0})
    saved_p = saved_prod[i]
    
    d_key = f"p_deliv_{i}_{asin_name}"
    b_key = f"p_buf_{i}_{asin_name}"
    s_key = f"p_ship_{i}_{asin_name}"

    if d_key not in st.session_state:
        try: st.session_state[d_key] = datetime.datetime.strptime(saved_p.get("deliv_date", ""), '%Y-%m-%d').date()
        except: st.session_state[d_key] = start_date + datetime.timedelta(days=15)
    if b_key not in st.session_state:
        st.session_state[b_key] = int(saved_p.get("buffer", 1))
    if s_key not in st.session_state:
        try: st.session_state[s_key] = datetime.datetime.strptime(saved_p.get("ship_date", ""), '%Y-%m-%d').date()
        except: st.session_state[s_key] = st.session_state[d_key] + datetime.timedelta(days=st.session_state[b_key])

    sync_fwd, sync_bwd = create_callbacks(d_key, b_key, s_key)

    with st.sidebar.expander(f"生产批次 {i+1} (手工预排参考)", expanded=False):
        saved_ch = saved_p.get("ch", "HQYD-海运快线-限时达")
        prod_index = ch_list.index(saved_ch) if saved_ch in ch_list else 3
        prod_ch = st.selectbox(f"手工预排渠道 {i+1}", ch_list, index=prod_index, key=f"p_ch_{i}_{asin_name}")
        
        p_deliv = st.date_input("🏭 预计交货日", key=d_key, on_change=sync_fwd)
        c_1, c_2 = st.columns([4, 6])
        p_buf = c_1.number_input("⏳几天后发", min_value=0, key=b_key, on_change=sync_fwd)
        p_ship = c_2.date_input("🚢开船/起飞(截单日)", key=s_key, on_change=sync_bwd)
        
        st.caption(f"🚀 轨迹: 预计 `{p_ship.strftime('%m-%d')}` 发车 + `{LOGISTICS_CHANNELS[prod_ch]}`天物流 + `{fba_delay}`天上架")

        prod_qty = st.number_input(f"批次数量 {i+1}", min_value=0, value=int(saved_p.get("qty", 0)), step=50, key=f"p_qty_{i}_{asin_name}")
        
        if prod_qty > 0 and prod_qty % box_qty != 0:
            lower, upper = prod_qty - (prod_qty % box_qty), prod_qty + (box_qty - (prod_qty % box_qty))
            st.warning(f"⚠️ `{prod_qty}件` 非整箱！建议: **`{lower}件`** 或 **`{upper}件`**")
            
        prod_state.append({"ch": prod_ch, "deliv_date": p_deliv.strftime('%Y-%m-%d'), "buffer": p_buf, "ship_date": p_ship.strftime('%Y-%m-%d'), "qty": prod_qty})
        
        if prod_qty > 0:
            days_to_ship = (p_ship - start_date).days
            prod_batches_raw.append({"id": i, "qty": prod_qty, "deliv_offset": days_to_ship, "manual_ch": prod_ch})

c1_p, c2_p = st.sidebar.columns(2)
if c1_p.button("➕ 增弹药槽", use_container_width=True, key=f"add_p_{asin_name}"): st.session_state[p_count_key] += 1; st.rerun()
if c2_p.button("➖ 删弹药槽", use_container_width=True, key=f"del_p_{asin_name}"):
    if st.session_state[p_count_key] > 1: st.session_state[p_count_key] -= 1; st.rerun()

# ================= 6. 侧边栏：新建发货分仓 =================
saved_new = c_data.get("new", [{"ch": "HQYD-海运-合德", "qty": 0, "lead": 35}] * 5)
n_count_key = f"n_count_{asin_name}"
if n_count_key not in st.session_state: st.session_state[n_count_key] = max(5, len(saved_new))

st.sidebar.subheader(f"3. 📝 新建发货分仓 ({st.session_state[n_count_key]}槽)")
global_lead = int(c_data.get("global_lead", 35))
global_lead_ui = st.sidebar.number_input("🏭 默认交期/备货(天)", min_value=0, value=global_lead, key=f"global_lead_{asin_name}")

def sync_lead_days(a_name):
    g_lead_ui = st.session_state[f"global_lead_{a_name}"]
    n_cnt = st.session_state.get(f"n_count_{a_name}", 5)
    c_date = st.session_state[f"start_date_{a_name}"]
    for idx in range(n_cnt):
        st.session_state[f"n_lead_{idx}_{a_name}"] = g_lead_ui
        st.session_state[f"n_anchor_{idx}_{a_name}"] = c_date
        st.session_state[f"n_orig_lead_{idx}_{a_name}"] = g_lead_ui

def force_update_all_anchors(a_name):
    n_cnt = st.session_state.get(f"n_count_{a_name}", 5)
    start_k = f"start_date_{a_name}"
    if start_k in st.session_state:
        for idx in range(n_cnt):
            lead_k = f"n_lead_{idx}_{a_name}"
            anchor_k = f"n_anchor_{idx}_{a_name}"
            orig_lead_k = f"n_orig_lead_{idx}_{a_name}"
            if lead_k in st.session_state:
                st.session_state[anchor_k] = st.session_state[start_k]
                st.session_state[orig_lead_k] = st.session_state[lead_k]

col_ctrl1, col_ctrl2 = st.sidebar.columns(2)
col_ctrl1.button("🔄 同步备货天数", use_container_width=True, on_click=sync_lead_days, args=(asin_name,))
col_ctrl2.button("🔄 全局刷新建单", use_container_width=True, on_click=force_update_all_anchors, args=(asin_name,), help="不改变现有天数，仅将所有草稿的建单日统一锁定为当前的推演起始日")

def draft_lead_changed(idx, a_name):
    lead_k = f"n_lead_{idx}_{a_name}"
    anchor_k = f"n_anchor_{idx}_{a_name}"
    orig_lead_k = f"n_orig_lead_{idx}_{a_name}"
    start_k = f"start_date_{a_name}"
    if lead_k in st.session_state and start_k in st.session_state:
        st.session_state[anchor_k] = st.session_state[start_k]
        st.session_state[orig_lead_k] = st.session_state[lead_k]

def force_update_anchor(idx, a_name):
    lead_k = f"n_lead_{idx}_{a_name}"
    anchor_k = f"n_anchor_{idx}_{a_name}"
    orig_lead_k = f"n_orig_lead_{idx}_{a_name}"
    start_k = f"start_date_{a_name}"
    if lead_k in st.session_state and start_k in st.session_state:
        st.session_state[anchor_k] = st.session_state[start_k]
        st.session_state[orig_lead_k] = st.session_state[lead_k]

new_state = []
user_new_batches = []
user_new_total_qty = 0

for i in range(st.session_state[n_count_key]):
    if i >= len(saved_new): 
        saved_new.append({"ch": "HQYD-海运-合德", "qty": 0, "lead": global_lead, "anchor_date": start_date.strftime('%Y-%m-%d'), "orig_lead": global_lead})
        
    anchor_k = f"n_anchor_{i}_{asin_name}"
    orig_lead_k = f"n_orig_lead_{i}_{asin_name}"
    lead_key = f"n_lead_{i}_{asin_name}"
    
    if anchor_k not in st.session_state:
        ad_str = saved_new[i].get("anchor_date", start_date.strftime('%Y-%m-%d'))
        try: st.session_state[anchor_k] = datetime.datetime.strptime(ad_str, '%Y-%m-%d').date()
        except: st.session_state[anchor_k] = start_date
        
    if orig_lead_k not in st.session_state:
        st.session_state[orig_lead_k] = int(saved_new[i].get("orig_lead", saved_new[i].get("lead", global_lead)))
        
    if lead_key not in st.session_state:
        expected = st.session_state[anchor_k] + datetime.timedelta(days=st.session_state[orig_lead_k])
        st.session_state[lead_key] = max(0, (expected - start_date).days)

    with st.sidebar.expander(f"发货分仓 {i+1}", expanded=(i==0)):
        saved_n_ch = saved_new[i].get("ch", "HQYD-海运-合德")
        new_index = ch_list.index(saved_n_ch) if saved_n_ch in ch_list else 5
        new_ch = st.selectbox(f"预定物流 {i+1}", ch_list, key=f"n_ch_{i}_{asin_name}", index=new_index)
        
        anchor_date = st.session_state[anchor_k]
        expected_ship = anchor_date + datetime.timedelta(days=st.session_state[orig_lead_k])
        label = f"距离发车(天) {i+1} [📌 {anchor_date.strftime('%m-%d')}建单 | 🚀 预计 {expected_ship.strftime('%m-%d')} 发]"
        
        c_lead1, c_lead2 = st.columns([6, 4])
        with c_lead1:
            new_lead = st.number_input(label, min_value=0, key=lead_key, on_change=draft_lead_changed, args=(i, asin_name))
        with c_lead2:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            st.button("🔄 刷新建单日", key=f"upd_anchor_{i}_{asin_name}", on_click=force_update_anchor, args=(i, asin_name), help="将此草稿的建单锚点强制刷新为当前的推演起始日")
            
        new_qty = st.number_input(f"计划发货数量 {i+1}", min_value=0, value=int(saved_new[i].get("qty", 0)), step=1, key=f"n_qty_{i}_{asin_name}")
        
        new_state.append({
            "ch": new_ch, 
            "qty": new_qty, 
            "lead": new_lead,
            "anchor_date": st.session_state[anchor_k].strftime('%Y-%m-%d'),
            "orig_lead": st.session_state[orig_lead_k]
        })
        
        if new_qty > 0 and new_qty % box_qty != 0:
            lower, upper = new_qty - (new_qty % box_qty), new_qty + (box_qty - (new_qty % box_qty))
            st.warning(f"⚠️ `{new_qty}件` 非整箱！建议: **`{lower}件`** 或 **`{upper}件`**")
            
        if new_qty > 0:
            user_new_total_qty += new_qty
            total_days_needed = new_lead + LOGISTICS_CHANNELS[new_ch] + fba_delay
            user_new_batches.append({"name": f"新单{i+1}:{new_ch.split('-')[-1]}", "qty": new_qty, "day": total_days_needed})
            st.caption(f"🚀 轨迹: `{new_lead}`天后发车 + `{LOGISTICS_CHANNELS[new_ch]}`天物流 + `{fba_delay}`天上架")

c1_n, c2_n = st.sidebar.columns(2)
if c1_n.button("➕ 增分仓槽", use_container_width=True, key=f"add_n_{asin_name}"): st.session_state[n_count_key] += 1; st.rerun()
if c2_n.button("➖ 删分仓槽", use_container_width=True, key=f"del_n_{asin_name}"):
    if st.session_state[n_count_key] > 1: st.session_state[n_count_key] -= 1; st.rerun()


# ================= 4.5 侧边栏：本地数据备份与恢复 =================
st.sidebar.divider()
st.sidebar.header("💾 个人存档保护 (防丢失必用)")

# 1. 核心魔法：实时抓取屏幕上的最新参数（完全无需点击保存）
current_live_data = {
    "initial_stock": initial_stock, "box_qty": box_qty, "start_date": start_date.strftime('%Y-%m-%d'),
    "fba_delay": fba_delay, 
    "region": st.session_state.get(f"ai_region_radio_{asin_name}", c_data.get("region", "US")).split(" ")[0].replace("🇺🇸", "US").replace("🇨🇦", "CA"),
    "global_sales": global_sales, "tolerance_days": tolerance_days, "cover_days": cover_days,
    "slicing_strategy": "全局" if "全局" in slicing_strategy else "单批次", "fast_pct": fast_pct,
    "phases": [{"name": p["name"], "end_date": p["end"].strftime('%Y-%m-%d'), "days": p["days"], "sales": p["sales"]} for p in phases],
    "fc": {"qty": fc_qty, "days": fc_days},
    "transit_list": transit_state, "prod": prod_state, "new": new_state
}

# 把屏幕上的最新数据，安全合并进整体历史档案中
export_configs = all_configs.copy()
export_configs[asin_name] = current_live_data

# 将合并好的最新状态直接转换成下载文件流
live_json_string = json.dumps(export_configs, ensure_ascii=False, indent=4)

st.sidebar.download_button(
    label="📥 1. 一键下载最新进度到电脑",
    data=live_json_string,
    file_name=f"备货推演存档_{datetime.date.today()}.json",
    mime="application/json",
    help="直接下载当前屏幕上最新的所有数据！无需再点右侧的保存按钮。"
)

# 2. 允许用户上传本地的备份恢复进度
uploaded_file = st.sidebar.file_uploader("📤 2. 上传本地存档文件恢复", type="json")
if uploaded_file is not None:
    try:
        data = json.load(uploaded_file)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        st.sidebar.success("✅ 数据恢复成功！请点击上方工具栏的 [⋮] -> [Clear cache] 后刷新页面。")
    except Exception as e:
        st.sidebar.error(f"❌ 读取存档失败: {e}")


# ================= 5. 数据存储层 =================
if st.session_state.get("trigger_save", False):
    data_to_save = {
        "initial_stock": initial_stock, "box_qty": box_qty, "start_date": start_date.strftime('%Y-%m-%d'),
        "fba_delay": fba_delay, 
        "region": st.session_state.get(f"ai_region_radio_{asin_name}", c_data.get("region", "US")).split(" ")[0].replace("🇺🇸", "US").replace("🇨🇦", "CA"),
        "global_sales": global_sales, "tolerance_days": tolerance_days, "cover_days": cover_days,
        "slicing_strategy": "全局" if "全局" in slicing_strategy else "单批次", "fast_pct": fast_pct,
        "phases": [{"name": p["name"], "end_date": p["end"].strftime('%Y-%m-%d'), "days": p["days"], "sales": p["sales"]} for p in phases],
        "fc": {"qty": fc_qty, "days": fc_days},
        "transit_list": transit_state, "prod": prod_state, "new": new_state,
        "view_mode": st.session_state[view_mode_key],
        "y_offset": st.session_state[y_offset_key]
    }
    save_config(asin_name, data_to_save)
    st.session_state["trigger_save"] = False
    st.success(f"✅ 【{asin_name}】 最新数据与策略参数已成功安全存档！")

# ================= 6. AI 大脑：双擎探测中枢 =================
with st.expander("🤖 V8.1 AI 资金杠杆调控与核验中枢 (点击展开查阅详细策略与矩阵)", expanded=False):
    saved_region = c_data.get("region", "US")
    pol_index = 0 if saved_region == "US" else 1
    ai_region_policy = st.radio("📍 目的国入库策略 (与 ASIN 独立绑定)：", 
                                ["🇺🇸 美国 (5分仓免配费动态矩阵)", "🇨🇦 加拿大 (单点多渠道锁仓)"], 
                                index=pol_index, horizontal=True, key=f"ai_region_radio_{asin_name}")
    region_code = "US" if "🇺🇸" in ai_region_policy else "CA"

    def get_first_drop_days(current_batches):
        t_15, t_0 = None, None
        temp_stock = initial_stock
        for d in range(1, 365):
            arr = [b for b in current_batches if b["day"] == d]
            for b in arr: temp_stock += b["qty"]
            # Fix V8.1: Array index matching Date correctly
            temp_stock -= daily_sales_array[d] if d < len(daily_sales_array) else global_sales
            safe_level = sum(daily_sales_array[d : d + 15])
            if temp_stock < safe_level and t_15 is None: t_15 = d
            if temp_stock < 0 and t_0 is None: t_0 = d
        return t_15 or 365, t_0 or 365

    def evaluate_core_t15(batches):
        temp_stock = initial_stock
        drop_periods = []
        current_drop = None

        for d in range(1, 366):
            arr = [b for b in batches if b["day"] == d]
            for b in arr: temp_stock += b["qty"]
            
            # Fix V8.1: Sync array index with actual offset day
            sales_today = daily_sales_array[d] if d < len(daily_sales_array) else global_sales
            temp_stock -= sales_today

            safe_level = 0
            for sd in range(d, d + 15):
                safe_level += daily_sales_array[sd] if sd < len(daily_sales_array) else global_sales

            is_drop = temp_stock < safe_level
            is_zero = temp_stock < 0

            if is_drop:
                if current_drop is None:
                    current_drop = {"start": d, "hit_zero": is_zero, "zero_day": d if is_zero else 365}
                else:
                    if is_zero:
                        current_drop["hit_zero"] = True
                        if current_drop["zero_day"] == 365:
                            current_drop["zero_day"] = d
            else:
                if current_drop is not None:
                    drop_periods.append(current_drop)
                    current_drop = None

        if current_drop is not None:
            drop_periods.append(current_drop)

        if not drop_periods:
            return 365, 365

        for dp in drop_periods:
            if dp["hit_zero"]:
                return dp["start"], dp["zero_day"]

        return drop_periods[-1]["start"], drop_periods[-1]["zero_day"]

    def calc_strict_matrix(total_boxes, f_pct, t_15_init, t_0_init, region, base_lead):
        res_lines = []
        res_plan = []
        if total_boxes <= 0: return res_lines, res_plan
        
        seas = {k: v for k, v in LOGISTICS_CHANNELS.items() if k in CH_CLASSIFICATION[region]["SEA"]}
        if not seas: seas = LOGISTICS_CHANNELS
        
        fast_seas = {k: v for k, v in seas.items() if v <= FAST_SEA_THRESHOLD}
        slow_seas = {k: v for k, v in seas.items() if v > FAST_SEA_THRESHOLD}
        if not slow_seas: slow_seas = fast_seas
        if not fast_seas: fast_seas = slow_seas
        
        sorted_fast_cheap = sorted(fast_seas.items(), key=lambda x: x[1], reverse=True)
        sorted_slow_cheap = sorted(slow_seas.items(), key=lambda x: x[1], reverse=True)
        fastest_ch = min(seas.items(), key=lambda x: x[1])[0]
        
        fast_boxes_target = round(total_boxes * (f_pct / 100.0))
        boxes_list = []
        
        if region == "US":
            if total_boxes < 5: total_boxes = 5
            base_b = total_boxes // 5
            rem_b = total_boxes % 5
            boxes_list = [base_b + 1] * rem_b + [base_b] * (5 - rem_b)
        else:
            f_b = fast_boxes_target
            s_b = total_boxes - f_b
            if f_b > 0: boxes_list.append(f_b)
            if s_b > 0: boxes_list.append(s_b)

        actual_fast_b = 0
        actual_slow_b = 0
        intended_f_b = 0
        current_t15 = t_15_init
        
        for i, s_box in enumerate(boxes_list):
            tgt_transit = current_t15 - base_lead - fba_delay
            
            is_intended_fast = False
            if intended_f_b < fast_boxes_target:
                is_intended_fast = True
                intended_f_b += s_box
                
            assigned_ch = fastest_ch
            is_actual_fast = True
            
            if not is_intended_fast:
                valid_slows = [c for c, t in sorted_slow_cheap if t <= tgt_transit]
                if valid_slows:
                    assigned_ch = valid_slows[0]
                    is_actual_fast = False
                else:
                    valid_fasts = [c for c, t in sorted_fast_cheap if t <= tgt_transit]
                    if valid_fasts: assigned_ch = valid_fasts[0]
                    else: assigned_ch = fastest_ch
                    is_actual_fast = True
            else:
                valid_fasts = [c for c, t in sorted_fast_cheap if t <= tgt_transit]
                if valid_fasts: assigned_ch = valid_fasts[0]
                else: assigned_ch = fastest_ch
                is_actual_fast = True
                
            if is_actual_fast:
                actual_fast_b += s_box
                prefix = "⚡ 先锋"
            else:
                actual_slow_b += s_box
                prefix = "🐢 主力"
                
            res_plan.append((assigned_ch, s_box * box_qty))
            res_lines.append(f"> {prefix}矩阵 (货件{i+1}): 建议 `{s_box * box_qty}件 ({s_box}箱)` 走 **[{assigned_ch}]**。")
            
            actual_transit_time = LOGISTICS_CHANNELS[assigned_ch]
            actual_arrival_day = base_lead + actual_transit_time + fba_delay
            lifespan_days = (s_box * box_qty) / max(1, global_sales)
            current_t15 = max(current_t15, actual_arrival_day) + lifespan_days

        actual_fast_pct = round((actual_fast_b / sum(boxes_list)) * 100) if boxes_list else 0
        actual_slow_pct = 100 - actual_fast_pct
        
        if actual_fast_b > fast_boxes_target:
            warning_msg = f"⚠️ **护盘强制调控**：为确保所有货件能在 T15 防线前入库，系统被迫将部分慢船升级为快船！\n> 🎯 设定资金比例：快船 {f_pct}% | 慢船 {100-f_pct}%\n> 📊 **实际执行比例：快船 {actual_fast_pct}% | 慢船 {actual_slow_pct}%**"
            res_lines.insert(0, warning_msg)
        else:
            success_msg = f"✅ **资金比例完美达标**：\n> 🎯 设定资金比例：快船 {f_pct}% | 慢船 {100-f_pct}%\n> 📊 **实际执行比例：快船 {actual_fast_pct}% | 慢船 {actual_slow_pct}%**"
            res_lines.insert(0, success_msg)
            
        return res_lines, res_plan

    base_t_15, _ = evaluate_core_t15(baseline_batches)
    final_sim_batches = baseline_batches.copy()

    base_total_qty = initial_stock + sum(b['qty'] for b in baseline_batches)
    base_total_box = math.ceil(base_total_qty / box_qty)
    base_date_str = (start_date + datetime.timedelta(days=base_t_15)).strftime('%Y-%m-%d')

    prod_batches_sorted = sorted(prod_batches_raw, key=lambda x: x["deliv_offset"])
    est_total_need = sum(b["qty"] for b in prod_batches_sorted)

    if base_t_15 >= 360:
        st.info(f"✅ **【基础安全水位溯源】**：基于纯物理流水（在库+预留+在途，共计 `{base_total_qty}件 ({base_total_box}箱)`），大盘在未来 360 天内均处于绝对健康状态，完全不会跌穿安全线。")
        ai_prod_batches = [{"name": f"采购{b['id']+1}:{b['manual_ch'].split('-')[-1]}", "qty": b["qty"], "day": b["deliv_offset"] + LOGISTICS_CHANNELS[b["manual_ch"]] + fba_delay} for b in prod_batches_raw]
        for ab in ai_prod_batches: final_sim_batches.append(ab)
        ai_new_qty, user_new_total_qty, effective_fast_pct = 0, 0, fast_pct
    else:
        test_batches = baseline_batches + [{"qty": b["qty"], "day": b["deliv_offset"] + 30} for b in prod_batches_sorted]
        ai_eval_t_15, _ = evaluate_core_t15(test_batches)

        new_need_qty = max(0, sum(daily_sales_array[ai_eval_t_15 : ai_eval_t_15 + cover_days]))
        
        if "全局" in slicing_strategy:
            total_pool = est_total_need + new_need_qty
            target_fast_vol = total_pool * (fast_pct / 100.0)
            remaining_fast = max(0, target_fast_vol - est_total_need)
            effective_fast_pct = 0 if new_need_qty == 0 else min(100, round((remaining_fast / new_need_qty) * 100))
        else:
            effective_fast_pct = fast_pct
            
        ai_prod_reports = []
        ai_prod_batches = []
        current_sim_batches = baseline_batches.copy()
        
        for pb in prod_batches_sorted:
            cur_t_15, cur_t_0 = evaluate_core_t15(current_sim_batches)
            t_15_max = cur_t_15 - pb["deliv_offset"] - fba_delay
            t_0_max  = cur_t_0 - pb["deliv_offset"] - fba_delay 
            
            best_ch, is_air, reason = get_best_channel(t_15_max, t_0_max, tolerance_days, region_code)
            
            user_ch = pb["manual_ch"]
            final_boxes = math.ceil(pb["qty"]/box_qty)
            fee_warn = ""
            if region_code == "US" and not is_air and final_boxes < 5:
                final_boxes = 5
                fee_warn = " *(强扩至5箱防配费)*"
                
            final_qty = final_boxes * box_qty
            arr_day = pb["deliv_offset"] + LOGISTICS_CHANNELS[user_ch] + fba_delay
            sim_batch = {"name": f"采购{pb['id']+1}:{user_ch.split('-')[-1]}", "qty": final_qty, "day": arr_day, "hide_label": False}
            ai_prod_batches.append(sim_batch)
            current_sim_batches.append(sim_batch)
            
            if user_ch == best_ch:
                status = "🟢 完美吻合最优解" if reason in ["P1", "P2"] else ("🟡 容忍降速" if "P3" in reason else "🚨 极速空运")
                ai_prod_reports.append(f"* **批次 {pb['id']+1}**：预排 [{user_ch}] 产出 `{final_qty}件 ({final_boxes}箱)`{fee_warn} $\\rightarrow$ {status}。")
            else:
                time_diff = LOGISTICS_CHANNELS[user_ch] - LOGISTICS_CHANNELS[best_ch]
                if time_diff > 0:
                    ai_prod_reports.append(f"* **批次 {pb['id']+1}**：预排 [{user_ch}] 产出 `{final_qty}件 ({final_boxes}箱)`{fee_warn} $\\rightarrow$ ⚠️ **存在断货风险！** AI强烈建议改发 **[{best_ch}]**。")
                else:
                    ai_prod_reports.append(f"* **批次 {pb['id']+1}**：预排 [{user_ch}] 产出 `{final_qty}件 ({final_boxes}箱)`{fee_warn} $\\rightarrow$ 💡 **运费溢出浪费！** 经测算完全可走更便宜的 **[{best_ch}]**。")

        final_sim_batches = current_sim_batches.copy()
        ai_final_target_t15, final_t_0_cliff = evaluate_core_t15(current_sim_batches)
            
        demand_cover_qty = sum(daily_sales_array[ai_final_target_t15 : ai_final_target_t15 + cover_days])
        
        ai_new_boxes = math.ceil(demand_cover_qty / box_qty)
        ai_new_qty = ai_new_boxes * box_qty
        
        st.info(f"**【基础安全水位溯源】**：基于纯物理流水（在库+预留+在途，共计 `{base_total_qty}件 ({base_total_box}箱)`），大盘预计于 `{base_t_15}` 天后 ({base_date_str}) 跌穿 15天安全防线。")
        
        if "全局" in slicing_strategy:
            st.info(f"⚖️ **统筹策略 [全局总盘子] 生效中**：系统已用老货抵扣快船配额。本次新单可用快船基准比例动态修正为：**{effective_fast_pct}%** (原设定 {fast_pct}%)")
        else:
            st.info(f"⚖️ **统筹策略 [单批次独立] 生效中**：各批次独立结算。本次新单快船基准比例严格执行设定值：**{effective_fast_pct}%**")
            
        if ai_prod_reports:
            st.success("**【既有排产单 ·物流履约推演】**\n" + "\n".join(ai_prod_reports))

    def display_moq_and_matrix(ai_qty, ai_boxes, user_qty, user_boxes, t_15, t_0, reg, lead, eff_f_pct):
        ai_str = f"`{ai_qty}件 ({ai_boxes}箱)`"
        
        if ai_qty < MOQ_UNITS:
            st.write(f"⚠️ **MOQ 检测**：理论缺口不足 `{MOQ_UNITS}`件 起批要求。系统提供双轨方案供您前瞻参考：")
            moq_boxes = math.ceil(MOQ_UNITS / box_qty)
            moq_qty = moq_boxes * box_qty
            
            st.markdown(f"#### 方案A：独立成团满足 MOQ `{moq_qty}件 ({moq_boxes}箱)`")
            lines_a, plan_a = calc_strict_matrix(moq_boxes, eff_f_pct, t_15, t_0, reg, lead)
            for l in lines_a: st.write(l)
            
            st.markdown(f"#### 方案B：跨同事/店铺精益拼单 `{ai_qty}件 ({ai_boxes}箱)`")
            st.caption(f"*(如果您想极致释放现金流，且能找到拼单，此为保底矩阵)*")
            lines_b, plan_b = calc_strict_matrix(ai_boxes, eff_f_pct, t_15, t_0, reg, lead)
            for l in lines_b: st.write(l)
            
            c_btn1, c_btn2 = st.columns(2)
            c_btn1.button("⚡ 记录方案A至左侧草稿 (未来执行)", type="secondary", on_click=apply_ai_plan, args=(plan_a, lead), key=f"f_btnA_{asin_name}")
            c_btn2.button("⚡ 记录方案B至左侧草稿 (未来执行)", type="secondary", on_click=apply_ai_plan, args=(plan_b, lead), key=f"f_btnB_{asin_name}")
            
        else:
            lines, plan = calc_strict_matrix(ai_boxes, eff_f_pct, t_15, t_0, reg, lead)
            st.write(f"💡 **附：基于 `{reg}` 策略的 AI 多渠道平铺矩阵前瞻**：")
            for l in lines: st.write(l)
            st.button("⚡ 记录AI方案至左侧草稿 (未来执行)", type="secondary", on_click=apply_ai_plan, args=(plan, lead), key=f"f_btnC_{asin_name}")


    if ai_final_target_t15 < 360:
        final_date_str = (start_date + datetime.timedelta(days=ai_final_target_t15)).strftime('%Y-%m-%d')
        st.warning(f"**【供需偏离度智能核验】**")
        
        seas = {k: v for k, v in LOGISTICS_CHANNELS.items() if k in CH_CLASSIFICATION[region_code]["SEA"]}
        if not seas: seas = LOGISTICS_CHANNELS
        fastest_sea_time = min(seas.items(), key=lambda x: x[1])[1]
        fastest_sea_name = min(seas.items(), key=lambda x: x[1])[0]
        total_fastest_time = global_lead + fastest_sea_time + fba_delay
        deadline_offset = ai_final_target_t15 - total_fastest_time
        
        if deadline_offset > 0:
            deadline_date = start_date + datetime.timedelta(days=deadline_offset)
            st.write(f"（理论释义：系统叠加计算老订单后，大盘目标死线锁定在 {ai_final_target_t15} 天后 ({final_date_str})。按系统配置的最快海运（{fastest_sea_name} {fastest_sea_time}天 + 备货交期 {global_lead}天 + 上架 {fba_delay}天 = 共 {total_fastest_time}天）反推，**您的极限安全建单节点为 {deadline_offset} 天后 ({deadline_date.strftime('%Y-%m-%d')})**。系统基于此防线点为您动态推算出以下理论补货极值：）")
            
            st.success(f"✅ **【安全储备期：无需采购】** 经系统反推，您的资金目前极其充裕！建议您在 **{deadline_offset} 天后 ({deadline_date.strftime('%Y-%m-%d')})** 再来处理本批次采购计划。理论预估届时需补充 **`{ai_new_qty}件 ({ai_new_boxes}箱)`**。")
            st.write(f"💡 **未来采购策略预演**：假设您在 {deadline_date.strftime('%Y-%m-%d')} 当天按推荐单量准时建单，系统动态推演的分仓策略如下：")
            
            simulated_lead = global_lead + deadline_offset
            display_moq_and_matrix(ai_new_qty, ai_new_boxes, user_new_total_qty, math.ceil(user_new_total_qty/box_qty) if user_new_total_qty>0 else 0, ai_final_target_t15, final_t_0_cliff, region_code, simulated_lead, effective_fast_pct)
            
            if user_new_total_qty > 0:
                user_new_boxes = math.ceil(user_new_total_qty / box_qty)
                st.warning(f"⚠️ **防积压拦截触发**：您目前处于安全期，但今日仍在左侧强行填入了 `{user_new_total_qty}件 ({user_new_boxes}箱)` 的建单计划。不仅提前了 {deadline_offset}天 消耗现金流，且系统强烈建议【暂缓执行该计划】！等到该下单的那天，再来看策略。")
                
        else:
            st.write(f"（理论释义：系统叠加计算老订单后，大盘目标死线锁定在 {ai_final_target_t15} 天后 ({final_date_str})。按系统配置的最快海运（{fastest_sea_name} {fastest_sea_time}天 + 备货交期 {global_lead}天 + 上架 {fba_delay}天 = 共 {total_fastest_time}天）反推，**您的极限安全建单节点已透支 {abs(deadline_offset)} 天！** 系统基于此死线为您动态推算出以下理论补货极值：）")
            
            if ai_new_qty > 0:
                user_new_boxes = math.ceil(user_new_total_qty / box_qty)
                user_str = f"`{user_new_total_qty}件 ({user_new_boxes}箱)`"
                ai_str = f"`{ai_new_qty}件 ({ai_new_boxes}箱)`"
        
                if user_new_total_qty == 0:
                    st.error(f"🚨 **【缺口执行警报】**：您尚未在左侧录入建单计划！理论安全补货缺口为：**{ai_str}**。")
                    
                    if ai_new_qty < MOQ_UNITS:
                        st.write(f"⚠️ **MOQ 检测**：理论缺口不足 `{MOQ_UNITS}`件 起批要求。系统提供双轨方案供您决策：")
                        moq_boxes = math.ceil(MOQ_UNITS / box_qty)
                        moq_qty = moq_boxes * box_qty
                        
                        st.markdown(f"#### 方案A：独立成团满足 MOQ `{moq_qty}件 ({moq_boxes}箱)`")
                        lines_a, plan_a = calc_strict_matrix(moq_boxes, effective_fast_pct, ai_final_target_t15, final_t_0_cliff, region_code, global_lead)
                        for l in lines_a: st.write(l)
                        
                        st.markdown(f"#### 方案B：跨同事/店铺精益拼单 `{ai_new_qty}件 ({ai_new_boxes}箱)`")
                        st.caption(f"*(如果您想极致释放现金流，且能找到拼单，此为保底矩阵)*")
                        lines_b, plan_b = calc_strict_matrix(ai_new_boxes, effective_fast_pct, ai_final_target_t15, final_t_0_cliff, region_code, global_lead)
                        for l in lines_b: st.write(l)
                        
                        c_btn1, c_btn2 = st.columns(2)
                        c_btn1.button("⚡ 接管方案A (MOQ 独立发车)", type="primary", on_click=apply_ai_plan, args=(plan_a, global_lead), key=f"n_btnA_{asin_name}")
                        c_btn2.button("⚡ 接管方案B (小单精益拼车)", on_click=apply_ai_plan, args=(plan_b, global_lead), key=f"n_btnB_{asin_name}")
                        
                    else:
                        lines, plan = calc_strict_matrix(ai_new_boxes, effective_fast_pct, ai_final_target_t15, final_t_0_cliff, region_code, global_lead)
                        st.write(f"💡 **附：基于 `{region_code}` 策略的 AI 多渠道平铺矩阵参考**：")
                        for l in lines: st.write(l)
                        st.button("⚡ 矩阵接管：一键纯净覆写 AI 方案至左侧", type="primary", on_click=apply_ai_plan, args=(plan, global_lead), key=f"n_btnC_{asin_name}")
        
                else:
                    diff_boxes = user_new_boxes - ai_new_boxes
                    diff_qty = abs(diff_boxes) * box_qty
                    diff_str = f"`{diff_qty}件 ({abs(diff_boxes)}箱)`"
                    is_moq_intent = (ai_new_qty < MOQ_UNITS and MOQ_UNITS <= user_new_total_qty <= MOQ_UNITS + box_qty * 3)
                    
                    if is_moq_intent:
                        temp_all_batches = current_sim_batches + user_new_batches
                        day_start = min([b["day"] for b in user_new_batches]) if user_new_batches else ai_final_target_t15
                        day_end_0, _ = evaluate_core_t15(temp_all_batches)
                        moq_cover_days = max(0, day_end_0 - day_start)
                        date_start_str = (start_date + datetime.timedelta(days=day_start)).strftime('%m-%d')
                        date_end_str = (start_date + datetime.timedelta(days=day_end_0)).strftime('%m-%d')
                        
                        st.write(f"✅ **动机感知核验 (MOQ 对齐)**：系统识别到大盘实际缺口仅需 {ai_str}，您填入的 {user_str} 是为了踩中工厂 **{MOQ_UNITS}件 起批线** 的合理商业动作。")
                        
                        if day_end_0 >= 360:
                            st.write(f"💡 **真实存活期沙盘推演**：该批次首票预计于 `{day_start}天后 ({date_start_str})` 衔接入库。经推演，大盘将彻底续命至 **一年以上**，真实覆盖期长达 **300+ 天**。")
                        else:
                            st.write(f"💡 **真实存活期沙盘推演**：该批次首票预计于 `{day_start}天后 ({date_start_str})` 衔接入库。经推演，大盘将被续命至 `{day_end_0}天后 ({date_end_str})` 枯竭，**真实可覆盖销售期精准达 `{moq_cover_days} 天`**。")
                        
                        st.markdown(f"#### 方案A：执行合法存活储备 (执行您的起批单量 `{user_str}`)")
                        lines_user, plan_user = calc_strict_matrix(user_new_boxes, effective_fast_pct, ai_final_target_t15, final_t_0_cliff, region_code, global_lead)
                        for l in lines_user: st.write(l)
                        
                        st.markdown(f"#### 方案B：跨店铺拼单退路 (极限省钱 `{ai_str}`)")
                        st.caption("*(如果您想极致释放现金流，且能找到拼单，此为保底拼单矩阵)*")
                        lines_ai, plan_ai = calc_strict_matrix(ai_new_boxes, effective_fast_pct, ai_final_target_t15, final_t_0_cliff, region_code, global_lead)
                        for l in lines_ai: st.write(l)
                        
                        c_btn1, c_btn2 = st.columns(2)
                        c_btn1.button("⚡ 接管方案A (按我的数量生成极优阵型)", type="primary", on_click=apply_ai_plan, args=(plan_user, global_lead), key=f"m_btnA_{asin_name}")
                        c_btn2.button("⚡ 接管方案B (按拼单理论值生成极优阵型)", on_click=apply_ai_plan, args=(plan_ai, global_lead), key=f"m_btnB_{asin_name}")
        
                    else:
                        if diff_boxes > 1:
                            st.write(f"⚠️ **偏差核验**：您已决策录入 {user_str}。这比理论需求溢出了约 {diff_str}。存在资金冗余占用风险，建议复核确认！")
                            st.write(f"▼ 附：理论极值 {ai_str} 备货状态下的 AI 推荐护盘拆单解法：")
                        elif diff_boxes < -1:
                            st.write(f"⚠️ **偏差核验**：您已决策录入 {user_str}。这比理论需求短缺了约 {diff_str}。未来周期存在高危断层隐患，强烈建议加单！")
                            st.write(f"▼ 附：理论极值 {ai_str} 备货状态下的 AI 推荐护盘拆单解法：")
                        else:
                            st.write(f"✅ **偏差核验**：极致操盘！您填写的单量与 AI 算法极度吻合，逻辑闭环通过！")
                            st.write(f"▼ 附：{ai_str} 备货状态下的 AI 推荐多渠道平铺矩阵：")
                            
                        lines, plan = calc_strict_matrix(ai_new_boxes, effective_fast_pct, ai_final_target_t15, final_t_0_cliff, region_code, global_lead)
                        for l in lines: st.write(l)
                        
                        st.button("🔄 如果需要，您仍可点击一键覆写采用纯理论 AI 方案", on_click=apply_ai_plan, args=(plan, global_lead), key=f"o_btn_{asin_name}")

    else:
        next_t_15, _ = evaluate_core_t15(final_sim_batches)
        if next_t_15 >= 360:
            st.success("✅ **长线链条绝对闭环**：当前在手的所有排产计划已充分溢出，全线健康！")
        else:
            next_demand = sum(daily_sales_array[next_t_15 : next_t_15 + cover_days])
            next_boxes = math.ceil(next_demand / box_qty)
            slowest_sea = max(LOGISTICS_CHANNELS[ch] for ch in CH_CLASSIFICATION[region_code]["SEA"] if ch in LOGISTICS_CHANNELS)
            next_action_day_offset = next_t_15 - global_lead - fba_delay - slowest_sea
            
            if next_action_day_offset > 0:
                next_date = start_date + datetime.timedelta(days=next_action_day_offset)
                st.success(f"✅ **远期状态无虞**：您当前的弹药充沛，**【今日彻底无需采购】！** 请留存现金流。")
                st.write(f"💡 **战略雷达预估**：为了卡住最省钱的远洋慢船，下一波大宗安全补货起步节点预估为：约 `{next_action_day_offset}` 天后 (**{next_date.strftime('%m月%d日')}**)。届时理论需补充约 `{next_boxes*box_qty}件 ({next_boxes}箱)`。")

# ================= 7. 主力推演引擎与绘图 =================
final_all_batches = baseline_batches + ai_prod_batches + user_new_batches
total_phase_days = sum(p["days"] for p in phases)

temp_stock = initial_stock
hit_zero_day = 365
for d in range(1, 366):
    arr = [b for b in final_all_batches if b["day"] == d]
    for b in arr: temp_stock += b["qty"]
    # Fix V8.1: Array index correctly maps to Day D
    sales_today = daily_sales_array[d] if d < len(daily_sales_array) else global_sales
    temp_stock -= sales_today
    if temp_stock < 0:
        hit_zero_day = d
        break

max_batch_day = max([b["day"] for b in final_all_batches]) if final_all_batches else 0
simulation_days = max(max_batch_day + 15, total_phase_days + 15, hit_zero_day + 15)
simulation_days = min(365, simulation_days) 

inventory_list = []
current_stock = initial_stock
hit_zero_date = None

events = []
was_healthy = True
was_zero = False
current_drop_date = None
hit_zero_in_current_drop = False

for day in range(1, simulation_days + 1):
    current_date = start_date + datetime.timedelta(days=day)
    arrived_today = [b for b in final_all_batches if b["day"] == day]
    for b in arrived_today: current_stock += b["qty"] 
    # Fix V8.1: Perfect offset alignment
    sales_today = daily_sales_array[day] if day < len(daily_sales_array) else global_sales
    current_stock -= sales_today
    
    safety_stock = 0
    for sd in range(day, day + 15):
        # Fix V8.1: Perfect offset alignment
        safety_stock += daily_sales_array[sd] if sd < len(daily_sales_array) else global_sales
    
    inventory_list.append({"Day": day, "Date": current_date, "Remaining Stock": current_stock, "Safety Stock": safety_stock, "Daily Sales": sales_today})
    
    is_drop = current_stock < safety_stock
    is_zero = current_stock < 0
    
    if is_zero and hit_zero_date is None:
        hit_zero_date = current_date
        
    if is_drop and was_healthy:
        current_drop_date = current_date
        hit_zero_in_current_drop = False
        
    if is_zero and not was_zero:
        hit_zero_in_current_drop = True
        
    if not is_drop and not was_healthy:
        if current_drop_date is not None:
            events.append({'drop_date': current_drop_date, 'hit_zero': hit_zero_in_current_drop})
        current_drop_date = None
        
    was_healthy = not is_drop
    was_zero = not is_zero
    
if current_drop_date is not None:
    events.append({'drop_date': current_drop_date, 'hit_zero': hit_zero_in_current_drop})

df_plot = pd.DataFrame(inventory_list)

first_safety_drop_date = events[0]['drop_date'] if events else None
final_safety_drop_date = events[-1]['drop_date'] if events else None

target_date = None
if events:
    for ev in events:
        if ev['hit_zero']:
            target_date = ev['drop_date']
            break
    else:
        target_date = events[-1]['drop_date']

suggested_buy_date = None
if target_date:
    region_code_plot = "US" if "🇺🇸" in st.session_state.get(f"ai_region_radio_{asin_name}", c_data.get("region", "US")) else "CA"
    seas_plot = {k: v for k, v in LOGISTICS_CHANNELS.items() if k in CH_CLASSIFICATION[region_code_plot]["SEA"]}
    if not seas_plot: seas_plot = LOGISTICS_CHANNELS
    fastest_sea_time_plot = min(seas_plot.items(), key=lambda x: x[1])[1]
    global_lead_plot = int(c_data.get("global_lead", 35))
    fba_delay_plot = int(c_data.get("fba_delay", 5))
    total_days_back = global_lead_plot + fastest_sea_time_plot + fba_delay_plot
    suggested_buy_date = target_date - datetime.timedelta(days=total_days_back)

# 顶部指标卡渲染
c1, c2, c3, c4 = st.columns(4)
c1.metric("📦 预计未来总流水量", f"{sum(b.get('qty', 0) for b in final_all_batches)} 件")

if hit_zero_date: 
    c2.metric("🚨 彻底断货预警", hit_zero_date.strftime("%Y-%m-%d"), "跌破 0 库存", delta_color="inverse")
else: 
    c2.metric("✅ 彻底断货预警", "未断货", "安全", delta_color="normal")

if first_safety_drop_date: 
    if len(events) == 1:
        c3.metric("⚠️ 安全水位跌破", first_safety_drop_date.strftime("%Y-%m-%d"), "首次跌穿", delta_color="inverse")
    else:
        c3.metric("⚠️ 跌破危险阵痛期", f"{first_safety_drop_date.strftime('%m/%d')} 至 {final_safety_drop_date.strftime('%m/%d')}", "跨度区间", delta_color="inverse")
else: 
    c3.metric("✅ 安全水位预警", "健康", "高于安全线", delta_color="normal")
    
c4.metric("⏱️ 推演日历跨度", f"{simulation_days} 天", f"至 {df_plot['Date'].iloc[-1].strftime('%m-%d')}")

# V8.0 图表上方紧凑收纳控制器
st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
col_h1, col_h2, col_h3 = st.columns([7.5, 1.2, 1.3])
with col_h2:
    st.session_state[y_offset_key] = st.number_input("↕️ 错落间距(px)", min_value=30, max_value=300, value=st.session_state[y_offset_key], step=5, on_change=save_view_settings)
with col_h3:
    st.selectbox("👀 标签视图模式", 
                 ["极简悬浮模式 (推荐)", "展开节点详情 (错落防撞)"], 
                 key=view_mode_key, 
                 on_change=toggle_view_mode,
                 label_visibility="visible")
    is_minimal_view = "极简" in st.session_state[view_mode_key]

fig = go.Figure()
fig.add_trace(go.Scatter(x=df_plot["Date"], y=df_plot["Safety Stock"], mode='lines', name='15天安全库存线', line=dict(color='#ff922b', width=2, dash='dot'), fill='tozeroy', fillcolor='rgba(255, 146, 43, 0.08)'))
fig.add_trace(go.Scatter(x=df_plot["Date"], y=df_plot["Remaining Stock"], mode='lines', name='FBA可用库存', line=dict(color='#1f77b4', width=3, shape='spline'), customdata=df_plot["Daily Sales"], hovertemplate="<b>日期: %{x}</b><br>可用库存: %{y} 件<br>当前阶段预估日销: <b>%{customdata} 单</b><extra></extra>"))
fig.add_hline(y=0, line_dash="dash", line_color="red")

if first_safety_drop_date:
    y_val_first = df_plot[df_plot["Date"] == first_safety_drop_date]["Remaining Stock"].values[0]
    fig.add_annotation(x=first_safety_drop_date.strftime('%Y-%m-%d'), y=y_val_first, text=f"⚠️ {first_safety_drop_date.strftime('%m/%d')} 首次跌穿", showarrow=True, arrowhead=1, arrowcolor="#e67700", ax=0, ay=-40, bgcolor="#fff4e6", font=dict(color="#e67700"))
    
    if final_safety_drop_date and final_safety_drop_date != first_safety_drop_date:
        y_val_final = df_plot[df_plot["Date"] == final_safety_drop_date]["Remaining Stock"].values[0]
        fig.add_annotation(x=final_safety_drop_date.strftime('%Y-%m-%d'), y=y_val_final, text=f"⚠️ {final_safety_drop_date.strftime('%m/%d')} 末次跌穿", showarrow=True, arrowhead=1, arrowcolor="#e67700", ax=0, ay=-65, bgcolor="#fff4e6", font=dict(color="#e67700"))
    
    if suggested_buy_date:
        fig.add_annotation(
            x=suggested_buy_date.strftime('%Y-%m-%d'), 
            y=0.92,            # 锁定在距离图表底部 3% 的位置
            yref="paper",      # 核心魔法：开启“相对画布坐标”，无视具体的库存数值变化
            text=f"🛒 {suggested_buy_date.strftime('%m/%d')} 建议建单", 
            showarrow=False,   # 关闭箭头
            bgcolor="#e7f5ff", 
            font=dict(color="#1f77b4", size=12),
            bordercolor="#1f77b4",
            borderwidth=1,
            borderpad=4
        )
        fig.add_vline(x=suggested_buy_date.strftime('%Y-%m-%d'), line_dash="dot", line_color="rgba(31, 119, 180, 0.5)")

if hit_zero_date:
    fig.add_annotation(x=hit_zero_date.strftime('%Y-%m-%d'), y=0, text=f"🚨 {hit_zero_date.strftime('%m/%d')} 彻底断货!", showarrow=True, arrowhead=1, arrowcolor="red", ax=0, ay=-100, bgcolor="#ffe3e3", font=dict(color="red"))

colors = ["#f8f9fa", "#e9ecef", "#dee2e6", "#ced4da"]
for i, p in enumerate(phases):
    t_start = p["start"].strftime('%Y-%m-%d')
    t_end = (p["end"] + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    
    # 1. 依然画背景色块（放在底层，不遮挡曲线）
    fig.add_vrect(x0=t_start, x1=t_end, fillcolor=colors[i % len(colors)], opacity=0.5, layer="below", line_width=0)
    
    # 2. 独立渲染文字标签（默认在顶层，自带白色半透明遮罩底色）
    fig.add_annotation(
        x=t_start,
        y=1,               # 悬浮在图表顶部 100% 的高度
        yref="paper",         # 开启相对坐标，随屏幕自适应
        xanchor="left",       # 文字左对齐起始线
        yanchor="top",
        text=f"<b>{p['name']}</b><br><span style='font-size:12px; color:gray;'>{p['sales']}</span>",
        showarrow=False,      # 关闭箭头
        bgcolor="rgba(255, 255, 255, 0.8)", # 🌟核心：加一个 80% 不透明度的白色底板
        bordercolor="rgba(0,0,0,0.05)",     # 极淡的边框增加质感
        borderpad=4
    )

arrival_dict = {}
total_qty_dict = {}

for b in final_all_batches:
    if b.get("hide_label"): continue 
    arr_date = start_date + datetime.timedelta(days=b["day"])
    if arr_date not in arrival_dict: 
        arrival_dict[arr_date] = []
        total_qty_dict[arr_date] = 0
    arrival_dict[arr_date].append(f"{b['name']}({b['qty']}件)")
    total_qty_dict[arr_date] += b['qty']

base_ay = 45
step_ay = st.session_state[y_offset_key]
# V8.0 防撞阶梯扩容至 5 级，应对极限拥挤
height_cycle = [base_ay, base_ay + step_ay, base_ay + step_ay*2, base_ay + step_ay*3, base_ay + step_ay*4]
h_idx = 0

for d_date in sorted(arrival_dict.keys()):
    date_str = d_date.strftime('%Y-%m-%d')
    items = arrival_dict[d_date]
    total_qty = total_qty_dict[d_date]
    
    try:
        y_val = df_plot[df_plot["Date"] == d_date]["Remaining Stock"].values[0]
        current_ay = height_cycle[h_idx % len(height_cycle)]
        h_idx += 1
        
        if is_minimal_view:
            hover_text = "<br>".join(items)
            display_text = f"🟢 {d_date.strftime('%m/%d')} 上架<br><b>+{total_qty}件</b>"
            fig.add_annotation(x=date_str, y=y_val, text=display_text, hovertext=hover_text, showarrow=True, arrowhead=1, arrowcolor="#2b8a3e", arrowsize=1.5, ax=0, ay=current_ay, bgcolor="#ebfbee", bordercolor="#2b8a3e", font=dict(color="#2b8a3e", size=11))
        else:
            detail_text = "<br>+ ".join(items)
            display_text = f"🟢 {d_date.strftime('%m/%d')} 上架<br>+ {detail_text}"
            fig.add_annotation(x=date_str, y=y_val, text=display_text, showarrow=True, arrowhead=1, arrowcolor="#2b8a3e", arrowsize=1.5, ax=0, ay=current_ay, bgcolor="#ebfbee", bordercolor="#2b8a3e", font=dict(color="#2b8a3e", size=11))
            
        fig.add_vline(x=date_str, line_dash="dot", line_color="rgba(43, 138, 62, 0.3)")
    except IndexError: pass 

fig.update_layout(title=f"【{asin_name}】 动态资金统筹与库存推演沙盘", xaxis_title="真实日历 (Date)", yaxis_title="FBA 可用库存 (Units)", hovermode="x unified", height=650, margin=dict(t=50, b=50))
st.plotly_chart(fig, use_container_width=True)