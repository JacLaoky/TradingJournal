import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from notion_client import Client
from streamlit_autorefresh import st_autorefresh

# 1. 页面配置与 CSS 样式
st.set_page_config(page_title="Trading Dashboard", layout="wide")

# 每 60 秒自动刷新 (注意: 频繁全页面刷新可能会打断用户查看图表，可视情况关闭)
count = st_autorefresh(interval=60 * 1000, key="dataframerefresh")

hide_st_style = """
<style>
    .block-container { padding: 1rem 1rem 0rem 1rem !important; }
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    div[data-testid="stMetric"] {
        background-color: transparent !important;
        border: 1px solid rgba(128, 128, 128, 0.2);
        padding: 10px;
        border-radius: 8px;
        text-align: center;
    }
</style>
"""
st.markdown(hide_st_style, unsafe_allow_html=True)

# 2. 鉴权与参数设置
if "NOTION_TOKEN" not in st.secrets or "DATABASE_ID" not in st.secrets:
    st.error("请在 .streamlit/secrets.toml 中配置 NOTION_TOKEN 和 DATABASE_ID！")
    st.stop()

notion = Client(auth=st.secrets["NOTION_TOKEN"])
DATABASE_ID = st.secrets["DATABASE_ID"]

# 添加本金输入框，避免将数值写死在代码里
initial_capital = st.sidebar.number_input("Initial Capital ($)", value=18641.34, step=1000.0)

# 3. 获取数据（包含分页逻辑）
@st.cache_data(ttl=60)
def load_notion_data():
    try:
        db_info = notion.databases.retrieve(database_id=DATABASE_ID)
        if not db_info.get("data_sources"):
            st.error("此数据库未关联 Data Source。")
            return []
        
        data_source_id = db_info["data_sources"][0]["id"]
        
        results = []
        has_more = True
        next_cursor = None
        
        # 【优化】处理 Notion 分页限制，拉取超过 100 条的完整数据
        while has_more:
            response = notion.data_sources.query(
                data_source_id=data_source_id,
                start_cursor=next_cursor
            )
            results.extend(response.get("results", []))
            has_more = response.get("has_more", False)
            next_cursor = response.get("next_cursor")
            
        data = []
        for page in results:
            props = page["properties"]
            try:
                # Symbol
                symbol = "Unknown"
                if "Name" in props and props["Name"]["title"]:
                    symbol = props["Name"]["title"][0]["plain_text"]
                elif "Symbol" in props and props["Symbol"]["title"]:
                    symbol = props["Symbol"]["title"][0]["plain_text"]
                
                # P&L
                pnl_prop = props.get("Realized P&L", {})
                pnl = 0
                if pnl_prop.get("type") == "formula":
                    pnl = pnl_prop.get("formula", {}).get("number", 0)
                elif pnl_prop.get("type") == "number":
                    pnl = pnl_prop.get("number", 0)
                pnl = pnl or 0
                
                # Date
                date_prop = props.get("Trade Date", {}).get("date", {})
                trade_date = None
                if date_prop:
                    trade_date = date_prop.get("end") or date_prop.get("start")
                if not trade_date:
                    continue 
                
                # Result
                if pnl > 0: result = "Win"
                elif pnl < 0: result = "Loss"
                else: result = "Break Even"

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
    st.warning("未读取到交易数据。")
    st.stop()

# 4. 数据清洗计算
def process_dataframe(data, capital):
    df = pd.DataFrame(data)
    df['Date'] = pd.to_datetime(df['Date']).dt.normalize()
    df = df.sort_values(by='Date').reset_index(drop=True)
    
    df['Cumulative P&L'] = df['P&L'].cumsum()
    df['Equity'] = capital + df['Cumulative P&L']
    df['Return %'] = (df['Cumulative P&L'] / capital) * 100
    df['Month_Sort'] = df['Date'].dt.strftime('%Y-%m')
    df['Month'] = df['Date'].dt.strftime('%Y %b')
    return df

df = process_dataframe(raw_data, initial_capital)

# 5. 顶部 KPI 看板
total_pl = df['Cumulative P&L'].iloc[-1]
current_equity = df['Equity'].iloc[-1]
total_return = df['Return %'].iloc[-1]

c1, c2, c3, c4 = st.columns([1, 1, 1, 0.2])
c1.metric("Equity", f"${current_equity:,.2f}")
c2.metric("Total P&L", f"${total_pl:,.2f}", delta=f"{total_return:.2f}%")
c3.metric("Total Trades", len(df))
if c4.button("↻", help="强制刷新缓存"):
    st.cache_data.clear()
    st.rerun()

st.markdown("---")

# 6. 图表通用配置
def shared_layout(fig):
    fig.update_layout(
        margin=dict(l=0, r=0, t=20, b=0),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        height=400,
        showlegend=False,
        hovermode="x unified",
        dragmode='zoom', 
    )
    fig.update_xaxes(tickformat="%Y-%m-%d", showgrid=False)
    fig.update_yaxes(showgrid=True, gridcolor='rgba(128,128,128,0.2)')
    return fig

config_settings = {
    'displayModeBar': True,
    'displaylogo': False,
    'modeBarButtonsToRemove': ['lasso2d', 'select2d']
}

# 7. 【优化】使用 Streamlit Native Tabs 替代 Radio
tab1, tab2, tab3, tab4 = st.tabs(["📈 Account Growth", "📊 Daily P&L", "📅 Monthly Returns", "🎯 Win Rate"])

with tab1:
    start_date = df['Date'].min() - pd.Timedelta(days=1)
    start_row = pd.DataFrame([{'Date': start_date, 'Equity': initial_capital, 'Return %': 0.0}])
    
    daily_equity_df = df.groupby('Date').tail(1)[['Date', 'Equity', 'Return %']]
    growth_df = pd.concat([start_row, daily_equity_df], ignore_index=True)
    growth_df['Label_Equity'] = growth_df.apply(lambda x: f"${x['Equity']:,.0f}<br>({x['Return %']:+.1f}%)", axis=1)
    
    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(
        x=growth_df['Date'], y=growth_df['Equity'],
        mode='lines+markers+text',
        text=growth_df['Label_Equity'],
        textposition="top center",
        textfont=dict(size=10),
        line=dict(color='#00C805', width=2, shape='spline'),
        fill='tozeroy', fillcolor='rgba(0, 200, 5, 0.05)',
        customdata=growth_df['Return %'],
        hovertemplate='<b>Date</b>: %{x|%Y-%m-%d}<br><b>Equity</b>: $%{y:,.0f}<br><b>Return</b>: %{customdata:.2f}%<extra></extra>'
    ))
    fig1.add_hline(y=initial_capital, line_dash="dash", line_color="rgba(128,128,128,0.5)", annotation_text="Initial Capital", annotation_position="bottom right")
    st.plotly_chart(shared_layout(fig1), use_container_width=True, config=config_settings)

with tab2:
    daily_df = df.groupby('Date')['P&L'].sum().reset_index()
    daily_df['Daily Return %'] = (daily_df['P&L'] / initial_capital) * 100
    daily_df['Daily_Label'] = daily_df.apply(lambda x: f"${x['P&L']:,.2f}<br>({x['Daily Return %']:+.2f}%)", axis=1)
    colors = ['#00C805' if x >= 0 else '#FF3B30' for x in daily_df['P&L']]
    
    fig2 = go.Figure(go.Bar(
        x=daily_df['Date'], y=daily_df['P&L'],
        text=daily_df['Daily_Label'],
        textposition='outside',
        marker_color=colors,
        hovertemplate='<b>Date</b>: %{x|%Y-%m-%d}<br><b>Daily P&L</b>: $%{y:,.2f}<extra></extra>'
    ))
    st.plotly_chart(shared_layout(fig2), use_container_width=True, config=config_settings)

with tab3:
    monthly_df = df.groupby(['Month_Sort', 'Month'])['P&L'].sum().reset_index().sort_values('Month_Sort')
    monthly_df['Return %'] = (monthly_df['P&L'] / initial_capital) * 100
    monthly_df['Label'] = monthly_df.apply(lambda x: f"${x['P&L']:,.2f}<br>({x['Return %']:+.2f}%)", axis=1)
    colors = ['#00C805' if x >= 0 else '#FF3B30' for x in monthly_df['P&L']]
    
    fig3 = go.Figure(go.Bar(
        x=monthly_df['Month'], y=monthly_df['P&L'],
        marker_color=colors, text=monthly_df['Label'],
        textposition='outside',
        hovertemplate='<b>Month</b>: %{x}<br><b>Monthly P&L</b>: $%{y:,.2f}<extra></extra>'
    ))
    st.plotly_chart(shared_layout(fig3), use_container_width=True, config=config_settings)

with tab4:
    win_loss = df['Result'].value_counts()
    fig4 = px.pie(
        values=win_loss.values, names=win_loss.index, hole=0.6, 
        color=win_loss.index, color_discrete_map={'Win':'#00C805', 'Loss':'#FF3B30', 'Break Even': 'gray'}
    )
    fig4.update_layout(margin=dict(l=0, r=0, t=30, b=0), height=350, showlegend=True)
    st.plotly_chart(fig4, use_container_width=True, config=config_settings)