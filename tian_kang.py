import streamlit as st
import pandas as pd
from datetime import datetime

# --- 1. 雲端設定 (已更新為你的新表單 ID) ---
SHEET_ID = "1TcrNfnSKj7hMd0LOXipBD9eKAft6yU7YnhZNX6rtPhg"

def get_sheet_url(sheet_name):
    return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# --- 2. 核心功能：讀取資料並自動校正欄位 ---
def load_cloud_data(name):
    try:
        url = get_sheet_url(name)
        df = pd.read_csv(url)
        # 移除標題所有空格與換行，防止抓不到欄位
        df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
        return df.dropna(how='all', axis=0)
    except:
        return pd.DataFrame()

def main():
    st.title("☁️ 天康連鎖藥局 - 雲端管理系統")

    # 登入邏輯
    if 'auth' not in st.session_state:
        st.subheader("🔐 權限登入")
        user = st.text_input("帳號 (boss 或店號如 mgr_04)")
        if st.button("進入系統"):
            if user == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"): st.session_state.auth, st.session_state.shop = 3, user.split("_")[1]
            else: st.error("帳號不正確"); return
            st.rerun()
        return

    # --- 讀取雲端三大分頁 ---
    df_pay = load_cloud_data("salary_data")
    df_emp = load_cloud_data("emp_info")
    df_ins = load_cloud_data("ins_info")

    # 【自動校正欄位名】：模糊搜尋關鍵欄位
    col_mapping = {}
    for actual_col in df_pay.columns:
        if "月份" in actual_col: col_mapping[actual_col] = "月份"
        if "店別" in actual_col: col_mapping[actual_col] = "店別"
        if "姓名" in actual_col: col_mapping[actual_col] = "姓名"
    
    df_pay = df_pay.rename(columns=col_mapping)

    # 檢查基礎欄位
    if '月份' not in df_pay.columns or '店別' not in df_pay.columns:
        st.error("❌ 讀取失敗！請確認新表單的『salary_data』分頁第一行是否有『月份』和『店別』。")
        st.write("📊 目前偵測到的標題有：", list(df_pay.columns))
        return

    role = st.session_state.auth
    shop = st.session_state.shop
    
    tab1, tab2, tab3 = st.tabs(["💰 薪資核對與匯出", "👤 員工基本資料", "🏥 勞健保紀錄"])

    with tab1:
        # 月份篩選
        months = sorted(df_pay['月份'].unique().tolist()) if not df_pay.empty else ["2026-02"]
        target_month = st.sidebar.selectbox("處理月份", months)
        
        # 篩選資料
        df_pay['月份'] = df_pay['月份'].astype(str)
        df_pay['店別'] = df_pay['店別'].astype(str)
        mask = (df_pay['月份'].str.contains(str(target_month)))
        if role == 3: mask = mask & (df_pay['店別'] == shop)
        current_pay = df_pay[mask].copy()

        st.subheader(f"📍 {target_month} 核對清單 ({'總公司' if role==1 else f'{shop} 店'})")
        
        # 店長遮蔽權限
        mgr_cols = ["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]
        display_cols = current_pay.columns if role == 1 else [c for c in mgr_cols if c in current_pay.columns]
        
        st.data_editor(current_pay[display_cols], num_rows="dynamic", key="main_editor")

        # --- 老闆專屬：銀行檔匯出 ---
        if role == 1:
            st.divider()
            st.subheader("🏦 匯出銀行發薪檔 (自動合併個資)")
            pay_date = st.text_input("付款日期 (YYYYMMDD)", datetime.now().strftime("%Y%m%d"))
            
            if st.button("🚀 下載發薪清冊"):
                if not df_emp.empty:
                    # 合併 emp_info 裡的個資
                    final_df = current_pay.merge(df_emp[['姓名', '身分證', '收款帳號', '基本薪資合計']], on='姓名', how='left')
                    
                    # 計算金額：基本薪資合計 + 各項獎金
                    bonus_cols = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
                    for c in bonus_cols: 
                        if c in final_df.columns:
                            final_df[c] = pd.to_numeric(final_df[c], errors='coerce').fillna(0)
                        else:
                            final_df[c] = 0
                    
                    final_df['基本薪資合計'] = pd.to_numeric(final_df.get('基本薪資合計', 0), errors='coerce').fillna(0)
                    final_df['最終金額'] = final_df['基本薪資合計'] + final_df[bonus_cols].sum(axis=1)

                    # 銀行專用格式
                    bank_output = pd.DataFrame({
                        "付款日期": pay_date,
                        "姓名": final_df["姓名"],
                        "身分證號": final_df.get("身分證", "缺資料"),
                        "銀行帳號": final_df.get("收款帳號", "缺資料"),
                        "交易金額": final_df["最終金額"]
                    })
                    
                    csv = bank_output.to_csv(index=False).encode('utf-8-sig')
                    st.download_button(
                        label="📥 點我下載匯出檔 (.csv)",
                        data=csv,
                        file_name=f"TianKang_Bank_{target_month}.csv",
                        mime="text/csv"
                    )
                else:
                    st.error("❌ 找不到 emp_info 分頁資料，無法抓取身分證與帳號。")

    with tab2:
        st.subheader("👤 員工基本資料庫 (來源：emp_info)")
        st.dataframe(df_emp)

    with tab3:
        st.subheader("🏥 勞健保查詢 (來源：ins_info)")
        st.dataframe(df_ins)

if __name__ == "__main__":
    main()
