import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from notion_client import Client
from streamlit_autorefresh import st_autorefresh

# === 1. 页面配置 ===
st.set_page_config(page_title="Trading Dashboard", layout="wide")

# 自动刷新逻辑
count = st_autorefresh(interval=60 * 1000, key="dataframerefresh")

# --- 核心修改：CSS 样式注入 (解决"间距很空"的问题) ---
hide_st_style = """
<style>
    /* 1. 移除顶部巨大的空白区域 */
    .block-container {
        padding-top: 0rem !important;
        padding-bottom: 0rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        max-width: 100% !important;
    }
    
    /* 2. 隐藏 Header, Footer 和 汉堡菜单 */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* 3. 减少组件之间的默认垂直间距 */
    div[data-testid="stVerticalBlock"] {
        gap: 0.5rem !important;
    }
    
    /* 4. (可选) 让 Metric 指标更紧凑 */
    div[data-testid="stMetric"] {
        background-color: #f9f9f9; /* 给指标加个淡淡的背景，像卡片 */
        padding: 10px;
        border-radius: 5px;
        text-align: center;
    }
</style>
"""
st.markdown(hide_st_style, unsafe_allow_html=True)

# === 2. Notion 连接设置 (保持不变) ===
try:
    # 兼容本地开发和云端部署
    if "NOTION_TOKEN" in st.secrets:
        notion = Client(auth=st.secrets["NOTION_TOKEN"])
        DATABASE_ID = st.secrets["DATABASE_ID"]
    else:
        st.warning("未检测到 Secrets，请检查配置。")
        st.stop()
except FileNotFoundError:
    st.error("请配置 .streamlit/secrets.toml 文件！")
    st.stop()

# === 3. 获取并清洗 Notion 数据 (保持不变) ===
@st.cache_data(ttl=60)
def load_notion_data():
    try:
        db_info = notion.databases.retrieve(database_id=DATABASE_ID)
        if not db_info.get("data_sources"):
            # 兼容：如果不是 Data Source 数据库，尝试直接 query
            pass 
        
        # 尝试使用 query (兼容普通数据库)
        response = notion.databases.query(database_id=DATABASE_ID)
        results = response.get("results")
        
        data = []
        for page in results:
            props = page["properties"]
            try:
                # 1. 获取 Symbol
                symbol = "Unknown"
                if "Name" in props and props["Name"]["title"]:
                    symbol = props["Name"]["title"][0]["plain_text"]
                elif "Symbol" in props and props["Symbol"]["title"]:
                    symbol = props["Symbol"]["title"][0]["plain_text"]
                
                # 2. 获取 P&L
                pnl = 0
                if "P&L" in props:
                    pnl = props["P&L"].get("number", 0)
                if pnl is None: pnl = 0
                
                # 3. 获取 Date
                trade_date = None
                if "Trade Date" in props and props["Trade Date"]["date"]:
                    date_obj = props["Trade Date"]["date"]
                    trade_date = date_obj.get("end") or date_obj.get("start")
                elif "Date" in props and props["Date"]["date"]:
                    date_obj = props["Date"]["date"]
                    trade_date = date_obj.get("end") or date_obj.get("start")
                
                if not trade_date: continue

                # 4. Result
                result = "Win" if pnl > 0 else "Loss"
                if pnl == 0: result = "Break Even"

                data.append({
                    "Symbol": symbol,
                    "Date": trade_date,
                    "P&L": pnl,
                    "Result": result
                })
                
            except Exception as e:
                continue
                
        return data
        
    except Exception as e:
        st.error(f"连接 Notion 失败: {e}")
        return []

raw_data = load_notion_data()

if not raw_data:
    st.info("暂无数据或无法连接 Notion。")
    if st.button("重试"):
        st.cache_data.clear()
        st.rerun()
    st.stop()

# === 4. 数据处理 (保持不变) ===
initial_capital = 18600

def process_dataframe(data, capital):
    df = pd.DataFrame(data)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values(by='Date')
    df['Cumulative P&L'] = df['P&L'].cumsum()
    df['Equity'] = capital + df['Cumulative P&L']
    df['Return %'] = (df['Cumulative P&L'] / capital) * 100
    df['Label_Equity'] = df.apply(lambda x: f"${x['Equity']:,.0f}", axis=1) # 简化标签，太长会乱
    df['Month'] = df['Date'].dt.strftime('%Y-%m')
    return df

df = process_dataframe(raw_data, initial_capital)

# === 5. 顶部 KPI (紧凑布局) ===
total_pl = df['Cumulative P&L'].iloc[-1]
current_equity = df['Equity'].iloc[-1]
total_return = df['Return %'].iloc[-1]

# 使用 columns 布局，并在 Notion 中通常显示在一行
c1, c2, c3, c4 = st.columns([1, 1, 1, 0.2]) # c4是刷新按钮占位
c1.metric("Equity", f"${current_equity:,.0f}")
c2.metric("Total P&L", f"${total_pl:,.0f}", delta=f"{total_return:.2f}%")
c3.metric("Trades", len(df))
if c4.button("↻"): # 极简刷新按钮
    st.cache_data.clear()
    st.rerun()

# === 6. 导航栏 (模仿图中的胶囊菜单) ===
# 相比 st.tabs，radio更省空间。如果有 st.pills (Streamlit 1.40+) 效果更好
# 这里使用 horizontal radio 模拟菜单
selected_tab = st.radio(
    "View:", 
    ["Account Growth", "Daily P&L", "Monthly Returns", "Win Rate"], 
    horizontal=True,
    label_visibility="collapsed" # 隐藏 "View:" 标签
)

st.markdown("---") # 细分割线

# === 7. 图表区域 (核心修改：去除边距) ===

# 通用图表配置函数：去除 Plotly 留白，透明背景
def minimal_layout(fig):
    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0), # 关键：把上下左右边距设为0
        paper_bgcolor='rgba(0,0,0,0)',    # 透明背景
        plot_bgcolor='rgba(0,0,0,0)',
        xaxis=dict(showgrid=False),       # 去掉网格线更像截图
        yaxis=dict(showgrid=True, gridcolor='rgba(200,200,200,0.2)'),
        height=350,                       # 固定高度，防止太高
        showlegend=False,
        hovermode="x unified"
    )
    return fig

if selected_tab == "Account Growth":
    # 模仿截图：曲线图
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df['Date'], y=df['Equity'],
        mode='lines',
        line=dict(color='#00C805', width=2, shape='spline'), # 平滑曲线
        fill='tozeroy',
        fillcolor='rgba(0, 200, 5, 0.05)' # 极淡的填充
    ))
    # 模仿截图：只在最后一点显示 Label，防止太乱
    fig.add_trace(go.Scatter(
        x=[df['Date'].iloc[-1]], y=[df['Equity'].iloc[-1]],
        mode='markers+text',
        text=[f"${df['Equity'].iloc[-1]:,.0f}"],
        textposition="top left",
        marker=dict(color='#00C805', size=8)
    ))
    fig = minimal_layout(fig)
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False}) # 隐藏工具栏

elif selected_tab == "Daily P&L":
    colors = ['#00C805' if x >= 0 else '#FF3B30' for x in df['P&L']]
    fig = go.Figure(go.Bar(
        x=df['Date'], y=df['P&L'],
        marker_color=colors
    ))
    fig = minimal_layout(fig)
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

elif selected_tab == "Monthly Returns":
    monthly_df = df.groupby('Month')['P&L'].sum().reset_index()
    colors = ['#00C805' if x >= 0 else '#FF3B30' for x in monthly_df['P&L']]
    fig = go.Figure(go.Bar(
        x=monthly_df['Month'], y=monthly_df['P&L'],
        marker_color=colors,
        text=monthly_df['P&L'].apply(lambda x: f"{x:,.0f}"),
        textposition='auto'
    ))
    fig = minimal_layout(fig)
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

elif selected_tab == "Win Rate":
    win_loss = df['Result'].value_counts()
    color_map = {'Win':'#00C805', 'Loss':'#FF3B30', 'Break Even': 'gray'}
    fig = px.pie(
        values=win_loss.values, names=win_loss.index,
        hole=0.6, # 甜甜圈图更现代
        color=win_loss.index, color_discrete_map=color_map
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=300,
        showlegend=True
    )
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})