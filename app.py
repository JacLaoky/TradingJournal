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

c1, c2, c3, c4 = st.columns([1, 1, 1, 0.2])
c1.metric("Equity", f"${current_equity:,.0f}")
c2.metric("Total P&L", f"${total_pl:,.0f}", delta=f"{total_return:.2f}%")
c3.metric("Trades", len(df))
if c4.button("↻"):
    st.cache_data.clear()
    st.rerun()

selected_tab = st.radio(
    "View:", 
    ["Account Growth", "Daily P&L", "Monthly Returns", "Win Rate"], 
    horizontal=True,
    label_visibility="collapsed" # 隐藏 "View:" 标签
)

st.markdown("---")

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