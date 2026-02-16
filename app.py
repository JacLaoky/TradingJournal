import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from notion_client import Client
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Trading Dashboard", layout="wide")

count = st_autorefresh(interval=60 * 1000, key="dataframerefresh")

hide_st_style = """
<style>
    .block-container {
        padding-top: 0rem !important;
        padding-bottom: 0rem !important;
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
    
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    
    div[data-testid="stMetric"] {
        background-color: transparent !important;
        border: 1px solid rgba(128, 128, 128, 0.2); /* 淡淡的边框 */
        padding: 10px;
        border-radius: 8px;
        text-align: center;
    }
    
    div[role="radiogroup"] {
        justify-content: center;
    }
</style>
"""
st.markdown(hide_st_style, unsafe_allow_html=True)

try:
    notion = Client(auth=st.secrets["NOTION_TOKEN"])
    DATABASE_ID = st.secrets["DATABASE_ID"]
except FileNotFoundError:
    st.error("请配置 .streamlit/secrets.toml 文件！")
    st.stop()

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

initial_capital = 18600

# === 5. 数据处理逻辑 (DataFrame) ===
def process_dataframe(data, capital):
    df = pd.DataFrame(data)
    df['Date'] = pd.to_datetime(df['Date'])

    df['Date'] = df['Date'].dt.normalize()
   
    df = df.sort_values(by='Date')
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
c3.metric("Total Trades", len(df))
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

def shared_layout(fig):
    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0), # 去除边距
        paper_bgcolor='rgba(0,0,0,0)',    # 透明背景
        plot_bgcolor='rgba(0,0,0,0)',
        height=350,
        showlegend=False,
        hovermode="x unified",
        # [关键修复] 允许缩放和平移
        dragmode='zoom', 
    )
    # [关键修复] 强制 X 轴格式，不显示小时/分钟
    fig.update_xaxes(
        tickformat="%Y-%m-%d",
        showgrid=False
    )
    fig.update_yaxes(
        showgrid=True, 
        gridcolor='rgba(128,128,128,0.2)'
    )
    return fig

config_settings = {
    'displayModeBar': True, # 开启工具栏
    'displaylogo': False,   # 隐藏 Plotly 广告 Logo
    'modeBarButtonsToRemove': ['lasso2d', 'select2d'] # 移除不常用的选择工具
}

if selected_tab == "Account Growth":
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df['Date'], y=df['Equity'],
        mode='lines',
        line=dict(color='#00C805', width=2, shape='spline'), # 平滑曲线
        fill='tozeroy',
        fillcolor='rgba(0, 200, 5, 0.05)',
        name="Equity"
    ))

    fig.add_hline(
        y=initial_capital, 
        line_dash="dash", 
        line_color="rgba(255, 255, 255, 0.5)", # 半透明白色（适应深色模式）
        annotation_text="Initial Capital", 
        annotation_position="bottom right"
    )
    
    fig.add_trace(go.Scatter(
        x=[df['Date'].iloc[-1]], y=[df['Equity'].iloc[-1]],
        mode='markers+text',
        text=[f"${df['Equity'].iloc[-1]:,.0f}"],
        textposition="top left",
        marker=dict(color='#00C805', size=8),
        name="Current"
    ))
    fig = shared_layout(fig)
    st.plotly_chart(fig, use_container_width=True, config=config_settings) # 隐藏工具栏

elif selected_tab == "Daily P&L":
    colors = ['#00C805' if x >= 0 else '#FF3B30' for x in df['P&L']]
    fig = go.Figure(go.Bar(
        x=df['Date'], y=df['P&L'],
        marker_color=colors
    ))
    fig = shared_layout(fig)
    st.plotly_chart(fig, use_container_width=True, config=config_settings)

elif selected_tab == "Monthly Returns":
    monthly_df = df.groupby('Month')['P&L'].sum().reset_index()
    colors = ['#00C805' if x >= 0 else '#FF3B30' for x in monthly_df['P&L']]
    fig = go.Figure(go.Bar(
        x=monthly_df['Month'], y=monthly_df['P&L'],
        marker_color=colors,
        text=monthly_df['P&L'].apply(lambda x: f"{x:,.0f}"),
        textposition='auto'
    ))
    fig = shared_layout(fig)
    st.plotly_chart(fig, use_container_width=True, config=config_settings)

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
    st.plotly_chart(fig, use_container_width=True, config=config_settings)