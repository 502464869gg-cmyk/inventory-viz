import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import datetime

# ================= 1. 核心业务逻辑配置 =================
DEFAULT_ASIN = "BFN-143"
DEFAULT_STOCK = 600
FACTORY_LEAD_TIME = 35  # 工厂默认生产交期(天)

# 新增加拿大专线，并保持美国线
LOGISTICS_CHANNELS = {
    # 美国线
    "HQYD-红单包税": 9,
    "HQYD-空加派(带电)": 18,
    "HQYD-空加派(普货)": 18,
    "HQYD-海运快线-限时达": 30,
    "HQYD-海运快线-限时达(卡派)": 32,
    "HQYD-海运-合德": 35,
    "HQYD-海运-合德(卡派)": 35,
    "HQYD-海运慢线": 45,
    "HQYD-海运海卡": 55,
    # 加拿大线
    "HQYD-加拿大红单包税": 9,
    "HQYD-加拿大空加派包税": 18,
    "HQYD-加拿大海运包税": 40,
    "HQYD-加拿大海运限时达包税": 33,
    "HQYD-加拿大海卡包税(卡派)": 55
}

# ================= 2. 页面基础渲染 & 顶部参数 =================
st.set_page_config(page_title="全景备货推演沙盘", layout="wide")
st.title("📦 亚马逊【全链路物流 & 多阶段需求】终极沙盘")
st.markdown("已集成：真实日历引擎 | 动态安全库存预警 | 上架缓冲计算 | 采购装箱校验 | 北美全干线")

st.divider()
st.subheader("🛠️ 基础盘配置")
col_b1, col_b2, col_b3, col_b4 = st.columns(4)
asin_name = col_b1.text_input("当前推演 ASIN", DEFAULT_ASIN)
initial_stock = col_b2.number_input("当前 FBA 实际可用库存", min_value=0, value=DEFAULT_STOCK)
box_qty = col_b3.number_input("📦 单箱装箱数 (用于防呆校验)", min_value=1, value=24)
start_date = col_b4.date_input("📅 推演起始日期", value=datetime.date(2026, 6, 8))

# ================= 3. 侧边栏：全局变量 & 需求侧 =================
st.sidebar.header("⚙️ 平台全局变量")
fba_delay = st.sidebar.number_input("⏳ 预计 FBA 上架延迟 (天)", min_value=0, value=5, help="物流签收后，直到转为可售状态的缓冲期")

st.sidebar.header("📈 需求侧：动态销售阶段定义")
phases = []
default_phases = [
    ("大促前夕维稳期", 14, 7), 
    ("Prime Day 冲锋", 4, 35), 
    ("大促后控盘期", 21, 6), 
    ("常规平销期", 30, 10)
]

for i in range(4):
    with st.sidebar.expander(f"⚙️ 第 {i+1} 阶段设置", expanded=(i<2)):
        p_name = st.text_input(f"阶段 {i+1} 名称", value=default_phases[i][0], key=f"p_name_{i}")
        p_days = st.number_input(f"[{p_name}] 持续天数", min_value=1, value=default_phases[i][1], key=f"p_days_{i}")
        p_sales = st.slider(f"[{p_name}] 日均销预估", min_value=0, max_value=150, value=default_phases[i][2], key=f"p_sales_{i}")
        phases.append({"name": p_name, "days": p_days, "sales": p_sales})

# 预先生成未来每天的销量数组（方便后续计算安全库存）
daily_sales_array = []
for p in phases:
    daily_sales_array.extend([p["sales"]] * p["days"])
daily_sales_array.extend([10] * 365) # 兜底策略：跑完配置阶段后，默认每天按 10 单延展

# ================= 4. 侧边栏：供给侧 (多批次) =================
st.sidebar.header("🚚 供给侧：在途与采购进度")
batches = []

# --- 新增模块: 亚马逊内部调拨/接收中 ---
st.sidebar.subheader("0. 🔄 FC 内部调拨 / 正在接收")
with st.sidebar.expander("展开设置后台预留库存", expanded=False):
    fc_qty = st.number_input("预留库总量 (FC Transfer)", min_value=0, value=0, step=50)
    fc_days = st.number_input("预估几天后全部可售", min_value=1, value=7)
    if fc_qty > 0:
        batches.append({"name": "内部调拨释放", "qty": fc_qty, "day": fc_days})

# --- 模块 A: 在途 ---
st.sidebar.subheader("1. 🚢 已发货在途 (海上/空中)")
with st.sidebar.expander("展开设置各渠道在途数量", expanded=False):
    for ch_name, ch_days in LOGISTICS_CHANNELS.items():
        qty = st.number_input(f"{ch_name} (物流{ch_days}天)", min_value=0, value=0, step=50, key=f"transit_{ch_name}")
        if qty > 0:
            total_days = ch_days + fba_delay # 物流天数 + FBA上架延迟
            batches.append({"name": f"在途:{ch_name.split('-')[-1]}", "qty": qty, "day": total_days})

# --- 模块 B: 采购中 ---
st.sidebar.subheader("2. 🏭 采购中库存 (工厂生产)")
for i in range(1, 3):
    with st.sidebar.expander(f"正在生产的批次 {i}", expanded=False):
        prod_ch = st.selectbox(f"计划物流渠道", list(LOGISTICS_CHANNELS.keys()), key=f"prod_ch_{i}")
        prod_rem_days = st.number_input(f"距离完工还剩(天)", min_value=0, value=15, key=f"prod_rem_{i}")
        prod_qty = st.number_input(f"此批次数量", min_value=0, value=0, step=50, key=f"prod_qty_{i}")
        if prod_qty > 0:
            total_days = prod_rem_days + LOGISTICS_CHANNELS[prod_ch] + fba_delay
            batches.append({"name": f"采购中:{prod_ch.split('-')[-1]}", "qty": prod_qty, "day": total_days})

# --- 模块 C: 新下采购单 ---
st.sidebar.subheader("3. 📝 新下采购单 (今日提报)")
for i in range(1, 3):
    with st.sidebar.expander(f"今天新下的订单 {i}", expanded=(i==1)):
        new_ch = st.selectbox(f"预定物流", list(LOGISTICS_CHANNELS.keys()), index=3, key=f"new_ch_{i}")
        new_qty = st.number_input(f"计划采购数量", min_value=0, value=(600 if i==1 else 0), step=1, key=f"new_qty_{i}")
        
        # 整箱校验警告
        if new_qty > 0 and new_qty % box_qty != 0:
            lower_box = new_qty - (new_qty % box_qty)
            upper_box = new_qty + (box_qty - (new_qty % box_qty))
            st.warning(f"⚠️ 校验: {new_qty} 非整箱！建议调为 **{lower_box}** 或 **{upper_box}** (装箱数 {box_qty} 的倍数)。")
            
        if new_qty > 0:
            total_days = FACTORY_LEAD_TIME + LOGISTICS_CHANNELS[new_ch] + fba_delay
            batches.append({"name": f"新单:{new_ch.split('-')[-1]}", "qty": new_qty, "day": total_days})

# ================= 5. 核心计算引擎 (真实日历对撞) =================
total_phase_days = sum(p["days"] for p in phases)
max_batch_day = max([b["day"] for b in batches]) if batches else 0
simulation_days = max(max_batch_day + 15, total_phase_days + 15)

inventory_list = []
current_stock = initial_stock
hit_zero_date = None
hit_safety_date = None

for day in range(1, simulation_days + 1):
    current_date = start_date + datetime.timedelta(days=day)
    
    # 1. 供给：判断今日是否有货上架 (物流 + FBA延迟 结束)
    arrived_today = [b for b in batches if b["day"] == day]
    for b in arrived_today:
        current_stock += b["qty"] 
        
    # 2. 需求：扣减今日销量
    sales_today = daily_sales_array[day - 1]
    current_stock -= sales_today
    
    # 3. 计算动态 15 天安全库存需求 (未来15天的总销量)
    # 注意：daily_sales_array 的索引比 day 慢 1，所以未来15天是 day 到 day+14
    safety_stock = sum(daily_sales_array[day : day + 15])
    
    inventory_list.append({
        "Day": day, 
        "Date": current_date, 
        "Remaining Stock": current_stock,
        "Safety Stock": safety_stock
    })
    
    # 4. 捕捉首次预警节点
    if current_stock < safety_stock and hit_safety_date is None:
        hit_safety_date = current_date
    if current_stock < 0 and hit_zero_date is None:
        hit_zero_date = current_date

df_plot = pd.DataFrame(inventory_list)

# ================= 6. 数据看板与预警 =================
st.divider()
c1, c2, c3, c4 = st.columns(4)
c1.metric("📦 预计未来补货总量", f"{sum(b['qty'] for b in batches)} 件")

if hit_zero_date:
    c2.metric("🚨 核心断货预警", hit_zero_date.strftime("%Y-%m-%d"), "跌破 0 库存", delta_color="inverse")
else:
    c2.metric("✅ 核心断货预警", "未断货", "安全度过", delta_color="normal")

if hit_safety_date:
    c3.metric("⚠️ 安全水位预警", hit_safety_date.strftime("%Y-%m-%d"), "跌破 15天安全线", delta_color="inverse")
else:
    c3.metric("✅ 安全水位预警", "库存健康", "高于安全线", delta_color="normal")

c4.metric("⏱️ 推演跨度", f"{simulation_days} 天", f"至 {df_plot['Date'].iloc[-1].strftime('%m-%d')}")

# ================= 7. Plotly 真实日历图表 =================
fig = go.Figure()

# 绘制 15天安全库存区域 (背景面)
fig.add_trace(go.Scatter(
    x=df_plot["Date"], y=df_plot["Safety Stock"],
    mode='lines', name='15天安全库存线',
    line=dict(color='#ff922b', width=2, dash='dot'),
    fill='tozeroy', fillcolor='rgba(255, 146, 43, 0.1)'
))

# 绘制主可用库存曲线
fig.add_trace(go.Scatter(
    x=df_plot["Date"], y=df_plot["Remaining Stock"],
    mode='lines', name='FBA可用库存',
    line=dict(color='#1f77b4', width=3, shape='spline')
))

# 绘制绝对 0 库存基准线
fig.add_hline(y=0, line_dash="dash", line_color="red")

# 雷达标注：跌穿节点 (已修复类型冲突：转为字符串)
if hit_safety_date:
    y_val = df_plot[df_plot["Date"] == hit_safety_date]["Remaining Stock"].values[0]
    fig.add_annotation(
        x=hit_safety_date.strftime('%Y-%m-%d'), y=y_val,
        text=f"⚠️ {hit_safety_date.strftime('%m/%d')} 跌破安全线",
        showarrow=True, arrowhead=1, arrowcolor="#e67700", arrowsize=2,
        bgcolor="#fff4e6", font=dict(color="#e67700")
    )

if hit_zero_date:
    fig.add_annotation(
        x=hit_zero_date.strftime('%Y-%m-%d'), y=0,
        text=f"🚨 {hit_zero_date.strftime('%m/%d')} 彻底断货!",
        showarrow=True, arrowhead=1, arrowcolor="red", arrowsize=2,
        bgcolor="#ffe3e3", font=dict(color="red")
    )

# 绘制销售阶段背景色块 (已修复类型冲突：转为字符串)
colors = ["#f8f9fa", "#e9ecef", "#dee2e6", "#ced4da"]
current_stage_date = start_date
for i, p in enumerate(phases):
    end_stage_date = current_stage_date + datetime.timedelta(days=p["days"])
    fig.add_vrect(
        x0=current_stage_date.strftime('%Y-%m-%d'), x1=end_stage_date.strftime('%Y-%m-%d'),
        fillcolor=colors[i % len(colors)], opacity=0.5, layer="below", line_width=0,
        annotation_text=p["name"], annotation_position="top left"
    )
    current_stage_date = end_stage_date

# 绘制物流到港/上架垂直标志线
arrival_dict = {}
for b in batches:
    arr_date = start_date + datetime.timedelta(days=b["day"])
    if arr_date in arrival_dict:
        arrival_dict[arr_date] += f"<br>+ {b['name']} ({b['qty']})"
    else:
        arrival_dict[arr_date] = f"📦 {b['name']} ({b['qty']})"

for d_date, text in arrival_dict.items():
    # 核心修复点：给 d_date 加上 .strftime('%Y-%m-%d')
    fig.add_vline(x=d_date.strftime('%Y-%m-%d'), line_dash="dash", line_color="#2b8a3e", 
                  annotation_text=text, annotation_position="bottom right")

fig.update_layout(
    title=f"【{asin_name}】 FBA 动态库存生命周期推演",
    xaxis_title="真实日历 (Date)", yaxis_title="FBA 可用库存 (Units)",
    hovermode="x unified", height=600, margin=dict(t=50, b=50)
)

st.plotly_chart(fig, use_container_width=True)
