import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import re

# --- 1. 雲端設定 ---
SHEET_ID = "1TcrNfnSKj7hMd0LOXipBD9eKAft6yU7YnhZNX6rtPhg"
PAY_SHEET = "salary_data"
EMP_SHEET = "emp_info"
INS_SHEET = "ins_info"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# 強力欄位清洗與格式化工具
def robust_clean(df):
    if df is None or df.empty: return pd.DataFrame()
    # 移除標題空格與換行
    df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
    
    # 標題模糊對應
    mapping = {}
    for c in df.columns:
        if "店別" in c or "店號" in c: mapping[c] = "店別"
        if "姓名" in c: mapping[c] = "姓名"
        if "月份" in c: mapping[c] = "月份"
    df = df.rename(columns=mapping)

    # 格式化店別：統一轉成 01, 04, 11 這種兩位數格式
    if "店別" in df.columns:
        def format_id(val):
            nums = re.findall(r'\d+', str(val))
            return nums[0].zfill(2) if nums else str(val).strip()
        df["店別"] = df["店別"].apply(format_id)
    return df

def main():
    st.title("🚀 天康連鎖藥局 - 全功能雲端管理系統")

    # 建立連線
    conn = st.connection("gsheets", type=GSheetsConnection)

    # --- 登入邏輯 ---
    if 'auth' not in st.session_state:
        user = st.text_input("帳號 (boss 或 mgr_04)")
        if st.button("進入系統"):
            if user == "boss":
                st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"):
                shop_id = re.findall(r'\d+', user)
                st.session_state.auth, st.session_state.shop = 3, shop_id[0].zfill(2) if shop_id else "00"
            else:
                st.error("帳號無效"); return
            st.rerun()
        return

    # --- 讀取三大分頁 ---
    df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl="0"))
    df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl="0"))
    df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl="0"))

    role = st.session_state.auth
    shop = st.session_state.shop

    # 側邊欄狀態
    st.sidebar.success(f"📍 登入身分：{'總公司' if role==1 else f'店長 ({shop}店)'}")
    if st.sidebar.button("登出系統"):
        del st.session_state['auth']
        st.rerun()

    tab1, tab2, tab3 = st.tabs(["💰 薪資作業與匯出", "👤 員工基本資料", "🏥 勞健保查詢"])

    # --- Tab 1: 薪資作業 ---
    with tab1:
        # A. 管理功能：只有老闆能開新月份
        if role == 1:
            with st.sidebar.expander("➕ [管理] 自動開啟新月份"):
                new_month = st.text_input("輸入新月份 (如 2026-04)", "2026-04")
                if st.button("確認寫入雲端"):
                    new_rows = pd.DataFrame({
                        "月份": [new_month] * len(df_emp),
                        "店別": df_emp["店別"],
                        "姓名": df_emp["姓名"],
                        "職務加給": 0, "加班津貼": 0, "店毛利成長獎金": 0,
                        "推廣獎金": 0, "輔具推廣獎金": 0, "慢籤成長獎金": 0, "備註": ""
                    })
                    updated_pay = pd.concat([df_pay, new_rows], ignore_index=True)
                    conn.update(worksheet=PAY_SHEET, data=updated_pay)
                    st.success(f"✅ {new_month} 名單已成功寫入 Google Sheet！"); st.rerun()

        # B. 篩選與編輯
        if not df_pay.empty and '月份' in df_pay.columns:
            months = sorted(df_pay['月份'].unique().tolist(), reverse=True)
            target_month = st.sidebar.selectbox("切換核對月份", months)
            
            mask = (df_pay['月份'] == target_month)
            if role == 3: mask = mask & (df_pay['店別'] == shop)
            current_pay = df_pay[mask].copy()

            st.subheader(f"📅 {target_month} 核對清單")
            
            # 店長遮蔽敏感欄位
            mgr_view = ["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]
            display_cols = current_pay.columns if role == 1 else [c for c in mgr_view if c in current_pay.columns]
            
            edited_df = st.data_editor(current_pay[display_cols], num_rows="dynamic", key="editor")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("💾 同步存檔至雲端"):
                    # 排除當前顯示的部分，再把編輯後的塞回去
                    save_mask = (df_pay['月份'] == target_month)
                    if role == 3: save_mask = save_mask & (df_pay['店別'] == shop)
                    others = df_pay[~save_mask]
                    final_save = pd.concat([others, edited_df], ignore_index=True)
                    conn.update(worksheet=PAY_SHEET, data=final_save)
                    st.success("✅ 雲端存檔成功！")

            # C. 銀行匯出 (老闆專屬)
            if role == 1:
                with col2:
                    if st.button("🚀 匯出網銀發薪檔"):
                        # 勾稽 emp_info 抓帳號、身分證、本薪
                        final_df = current_pay.merge(df_emp[['姓名', '身分證', '收款帳號', '基本薪資合計']], on='姓名', how='left')
                        
                        # 數值轉換
                        bonus_cols = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
                        for c in bonus_cols: final_df[c] = pd.to_numeric(final_df[c], errors='coerce').fillna(0)
                        final_df['基本薪資合計'] = pd.to_numeric(final_df['基本薪資合計'], errors='coerce').fillna(0)
                        
                        # 實領計算
                        final_df['實領'] = final_df['基本薪資合計'] + final_df[bonus_cols].sum(axis=1)

                        bank_csv = pd.DataFrame({
                            "付款日期": datetime.now().strftime("%Y%m%d"),
                            "轉帳項目": "901", "企業編號": "75440263",
                            "員工姓名": final_df["姓名"], "身分證字號": final_df["身分證"],
                            "收款帳號": final_df["收款帳號"], "交易金額": final_df["實領"],
                            "附言": "薪資", "付款性質": "02"
                        })
                        st.download_button("📥 下載銀行 CSV", bank_csv.to_csv(index=False).encode('utf-8-sig'), f"Bank_{target_month}.csv")
        else:
            st.warning("目前無資料，請先在側邊欄建立月份。")

    # --- Tab 2: 員工資料 (店長僅限看自己店) ---
    with tab2:
        st.subheader("👤 員工基本資料 (唯讀)")
        display_emp = df_emp[df_emp['店別'] == shop] if role == 3 else df_emp
        st.dataframe(display_emp)

    # --- Tab 3: 勞健保查詢 (店長僅限看自己店) ---
    with tab3:
        st.subheader("🏥 勞健保扣款明細 (唯讀)")
        if role == 3:
            my_names = df_emp[df_emp['店別'] == shop]['姓名'].tolist()
            st.dataframe(df_ins[df_ins['姓名'].isin(my_names)])
        else:
            st.dataframe(df_ins)

if __name__ == "__main__":
    main()
