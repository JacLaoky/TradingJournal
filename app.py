import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from notion_client import Client
from streamlit_autorefresh import st_autorefresh

# === 1. 页面配置 ===
st.set_page_config(page_title="Trading Dashboard", layout="wide")

count = st_autorefresh(interval=60 * 1000, key="dataframerefresh")

# 隐藏默认菜单
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            .block-container {padding-top: 1rem; padding-bottom: 0rem;} 
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# === 2. Notion 连接设置 ===
# 初始化 Notion 客户端
try:
    notion = Client(auth=st.secrets["NOTION_TOKEN"])
    DATABASE_ID = st.secrets["DATABASE_ID"]
except FileNotFoundError:
    st.error("请配置 .streamlit/secrets.toml 文件！")
    st.stop()

# === 3. 获取并清洗 Notion 数据 ===
@st.cache_data(ttl=60)  # 设置缓存60秒，避免频繁请求 Notion
def load_notion_data():
    try:
        db_info = notion.databases.retrieve(database_id=DATABASE_ID)
        # 查询数据库 (默认取前100条，如需更多需加分页逻辑)
        if not db_info.get("data_sources"):
            st.error("这个数据库没有关联 Data Source，无法查询。")
            return []
        
        data_source_id = db_info["data_sources"][0]["id"]

        response = notion.data_sources.query(data_source_id=data_source_id)
        results = response.get("results")
        
        data = []
        for page in results:
            props = page["properties"]
            
            # --- 提取逻辑 (请根据你Notion的实际列名微调) ---
            try:
                # 1. 获取 Symbol (Title属性)
                # 假设你的标题列叫 "Name" 或 "Symbol"
                symbol = "Unknown"
                if "Name" in props and props["Name"]["title"]:
                    symbol = props["Name"]["title"][0]["plain_text"]
                elif "Symbol" in props and props["Symbol"]["title"]: # 备用名
                    symbol = props["Symbol"]["title"][0]["plain_text"]
                
                # 2. 获取 P&L (Number属性)
                # 假设列名叫 "P&L"
                pnl = props.get("P&L", {}).get("number", 0)
                if pnl is None: pnl = 0
                
                # 3. 获取 Date (Date属性 - 优先取结束时间)
                # 假设列名叫 "Date"
                date_prop = props.get("Trade Date", {}).get("date", None)
                if date_prop:
                    # 如果有 end date (平仓日)，用 end；否则用 start
                    trade_date = date_prop.get("end") or date_prop.get("start")
                else:
                    continue # 如果没日期，跳过这行
                
                # 4. 自动判断 Result (Win/Loss)
                # 不需要Notion里有这个标签，直接根据钱算
                result = "Win" if pnl > 0 else "Loss"
                if pnl == 0: result = "Break Even"

                data.append({
                    "Symbol": symbol,
                    "Date": trade_date,
                    "P&L": pnl,
                    "Result": result
                })
                
            except Exception as e:
                # 打印错误但不停止程序，防止单行数据错误导致崩溃
                print(f"Skipping row error: {e}")
                continue
                
        return data
        
    except Exception as e:
        st.error(f"连接 Notion 失败: {e}")
        return []

# 加载数据
raw_data = load_notion_data()

# 如果没有数据，提示用户
if not raw_data:
    st.warning("未读取到数据，请检查 Database ID 或 Notion 内容。")
    st.stop()

# === 4. 侧边栏设置 ===
initial_capital = 18600
    
    # 添加强制刷新按钮
if st.button("🔄"):
    st.cache_data.clear()
    st.rerun()

# === 5. 数据处理逻辑 (DataFrame) ===
def process_dataframe(data, capital):
    df = pd.DataFrame(data)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values(by='Date')
    
    # --- 核心计算 ---
    df['Cumulative P&L'] = df['P&L'].cumsum()
    df['Equity'] = capital + df['Cumulative P&L']
    df['Return %'] = (df['Cumulative P&L'] / capital) * 100
    
    df['Label_Equity'] = df.apply(
        lambda x: f"${x['Equity']:,.0f}<br>({x['Return %']:+.1f}%)", axis=1
    )
    
    df['Month'] = df['Date'].dt.strftime('%Y-%m')
    return df

df = process_dataframe(raw_data, initial_capital)

# === 6. 顶部 KPI 指标 ===
total_pl = df['Cumulative P&L'].iloc[-1]
current_equity = df['Equity'].iloc[-1]
total_return = df['Return %'].iloc[-1]

c1, c2, c3 = st.columns(3)
c1.metric("Equity", f"${current_equity:,.0f}")
c2.metric("Total P&L", f"${total_pl:,.0f}", delta=f"{total_return:.2f}%")
c3.metric("Total Trades", len(df))

st.divider()

# === 7. 图表区域 ===
tabs = st.tabs(["Daily P&L", "Cumulative Curve", "Monthly Returns", "Win Rate"])

# --- Tab 1: Daily P&L ---
with tabs[0]:
    st.subheader("Daily P&L")
    colors = ['#00C805' if x >= 0 else '#FF3B30' for x in df['P&L']]
    fig_daily = go.Figure(go.Bar(
        x=df['Date'], y=df['P&L'],
        marker_color=colors,
        text=df['P&L'], textposition='outside'
    ))
    fig_daily.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig_daily, use_container_width=True)

# --- Tab 2: Cumulative Curve ---
with tabs[1]:
    st.subheader("Account Growth")
    fig_cum = go.Figure()
    fig_cum.add_trace(go.Scatter(
        x=df['Date'], 
        y=df['Equity'],
        mode='lines+markers+text',
        line=dict(color='#00C805', width=3, shape='spline'), # 绿色曲线
        fill='tozeroy',
        fillcolor='rgba(0, 200, 5, 0.1)', # 淡淡的绿色填充
        text=df['Label_Equity'],
        textposition="top left",
        textfont=dict(size=10)
    ))
    fig_cum.add_hline(y=initial_capital, line_dash="dash", line_color="gray", annotation_text="Initial Capital")
    fig_cum.update_layout(
        paper_bgcolor='rgba(0,0,0,0)', 
        plot_bgcolor='rgba(0,0,0,0)',
        yaxis_title="Account Balance",
        hovermode="x unified",
        margin=dict(t=20, b=20)
    )
    st.plotly_chart(fig_cum, use_container_width=True)

# --- Tab 3: Monthly Returns ---
with tabs[2]:
    st.subheader("Monthly Returns")
    monthly_df = df.groupby('Month')['P&L'].sum().reset_index()
    monthly_df['Return %'] = (monthly_df['P&L'] / initial_capital) * 100
    monthly_df['Label'] = monthly_df.apply(
        lambda x: f"${x['P&L']:,.0f}<br>({x['Return %']:+.1f}%)", axis=1
    )
    monthly_colors = ['#00C805' if x >= 0 else '#FF3B30' for x in monthly_df['P&L']]
    
    fig_month = go.Figure(go.Bar(
        x=monthly_df['Month'],
        y=monthly_df['P&L'],
        marker_color=monthly_colors,
        text=monthly_df['Label'],
        textposition='outside'
    ))
    fig_month.update_layout(
        paper_bgcolor='rgba(0,0,0,0)', 
        plot_bgcolor='rgba(0,0,0,0)',
        yaxis_title="Net P&L"
    )
    st.plotly_chart(fig_month, use_container_width=True)

# --- Tab 4: Win Rate ---
with tabs[3]:
    st.subheader("Win/Loss Distribution")
    win_loss_counts = df['Result'].value_counts()
    
    # 定义颜色映射，防止没有Loss时报错
    color_map = {'Win':'#00C805', 'Loss':'#FF3B30', 'Break Even': 'gray'}
    
    fig_pie = px.pie(
        values=win_loss_counts.values, 
        names=win_loss_counts.index, 
        hole=0.5,
        color=win_loss_counts.index,
        color_discrete_map=color_map
    )
    fig_pie.update_layout(paper_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig_pie, use_container_width=True)
