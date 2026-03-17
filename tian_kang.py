import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import re
import hashlib

# --- 1. 雲端與頁面設定 ---
SHEET_ID = "1TcrNfnSKj7hMd0LOXipBD9eKAft6yU7YnhZNX6rtPhg"
PAY_SHEET = "salary_data"
EMP_SHEET = "emp_info"
INS_SHEET = "ins_info"
ACC_SHEET = "user_accounts"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# --- 工具函數 ---
def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def robust_clean(df, expected_cols=None):
    if df is None or df.empty: return pd.DataFrame(columns=expected_cols if expected_cols else [])
    df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
    mapping = {
        "店別": "店別", "店號": "店別", "姓名": "姓名", "月份": "月份",
        "勞健保自負額": "勞健保自負額", "身分證": "身分證", "單位": "單位",
        "基本薪資合計": "基本薪資合計", "執照津貼": "執照津貼", "車資補貼": "車資補貼", "備註": "備註"
    }
    new_mapping = {}
    for c in df.columns:
        for k, v in mapping.items():
            if k in c: new_mapping[c] = v
    df = df.rename(columns=new_mapping)
    
    if expected_cols:
        for col in expected_cols:
            if col not in df.columns: 
                df[col] = 0 if any(x in col for x in ["獎金", "津貼", "合計", "補貼", "訪", "自負額"]) else ""
    
    if "單位" in df.columns: df["單位"] = df["單位"].astype(str).str.strip()
    if "店別" in df.columns:
        df["店別"] = df["店別"].apply(lambda x: re.findall(r'\d+', str(x))[0].zfill(2) if re.findall(r'\d+', str(x)) else str(x).strip())
    return df

def generate_bank_csv(df_source, df_employee, target_m):
    emp_subset = df_employee[['姓名', '身分證', '收款帳號']].drop_duplicates('姓名')
    f_df = df_source.merge(emp_subset, on='姓名', how='left')
    bank = pd.DataFrame({
        "付款日期": datetime.now().strftime("%Y%m%d"),
        "轉帳項目": "901", "企業編號": "75440263",
        "員工姓名": f_df["姓名"], "身分證字號": f_df["身分證"],
        "收款帳號": f_df["收款帳號"], "交易金額": f_df["應付金額"],
        "附言": "薪資", "付款性質": "02"
    })
    return bank.to_csv(index=False).encode('utf-8-sig')

def main():
    st.title("🚀 天康連鎖藥局 - 雙單位發薪管理系統")
    conn = st.connection("gsheets", type=GSheetsConnection)

    if st.sidebar.button("🔄 刷新雲端資料"):
        st.cache_data.clear(); st.rerun()

    # --- 定義獎金結構 ---
    PHARMACY_VAR = ['職務加給', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金', '加班津貼']
    CASE_MGR_VAR = ['電訪', '超額電訪', '家訪', '超額家訪', '三節獎金', '輔具獎金', '加班津貼']
    ALL_VAR_COLS = list(set(PHARMACY_VAR + CASE_MGR_VAR))

    # --- 讀取資料 ---
    try:
        df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl=300), expected_cols=['姓名', '單位', '店別', '身分證', '收款帳號', '基本薪資合計', '執照津貼', '車資補貼'])
        df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl=300), expected_cols=['月份', '店別', '姓名', '備註'] + ALL_VAR_COLS)
        df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl=300), expected_cols=['姓名', '月份', '勞健保自負額'])
        df_acc = robust_clean(conn.read(worksheet=ACC_SHEET, ttl=300))
    except Exception as e:
        st.error(f"❌ 雲端資料庫讀取失敗: {e}"); st.stop()

    # --- 登入控制 ---
    if 'auth' not in st.session_state:
        mode = st.radio("入口選擇", ["管理端登入", "員工查詢", "新帳號註冊"], horizontal=True)
        if mode == "管理端登入":
            acc = st.text_input("管理帳號"); pw = st.text_input("管理密碼", type="password")
            if st.button("進入後台"):
                match = df_acc[(df_acc['帳號'] == acc) & (df_acc['密碼'] == hash_password(pw))]
                if not match.empty:
                    if acc == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
                    elif acc == "acct": st.session_state.auth, st.session_state.shop = 4, "ACCOUNTING"
                    elif acc.startswith("mgr_"): st.session_state.auth, st.session_state.shop = 3, re.findall(r'\d+', acc)[0].zfill(2)
                    st.rerun()
                else: st.error("❌ 驗證失敗")
        return

    role = st.session_state.auth
    shop = st.session_state.shop

    tabs = st.tabs(["💰 薪資發薪作業", "👤 員工資料庫", "🏥 勞健保紀錄", "🔑 帳號管理"])
    
    with tabs[0]:
        # --- 老闆專屬管理功能 ---
        if role == 1:
            with st.sidebar.expander("🛠️ 月份名單管理"):
                # A. 建立新月份
                st.subheader("➕ 建立新月份")
                nm = st.text_input("輸入新月份 (如 2026-05)", "2026-05")
                if st.button("執行建立"):
                    initial_remarks = [""] * len(df_emp)
                    if not df_pay.empty and "備註" in df_pay.columns:
                        try:
                            latest_rem = df_pay.sort_values(['姓名','月份'], ascending=[True,False]).drop_duplicates('姓名')[['姓名','備註']]
                            df_t = df_emp[['姓名']].merge(latest_rem, on='姓名', how='left')
                            initial_remarks = df_t["備註"].fillna("").tolist()
                        except: pass
                    new_r = pd.DataFrame({"月份":[nm]*len(df_emp), "店別":df_emp["店別"], "姓名":df_emp["姓名"], "備註":initial_remarks})
                    for c in ALL_VAR_COLS: new_r[c] = 0
                    conn.update(worksheet=PAY_SHEET, data=pd.concat([df_pay, new_r], ignore_index=True))
                    st.cache_data.clear(); st.success(f"✅ {nm} 建立成功"); st.rerun()
                
                st.markdown("---")
                
                # B. 【新功能】刪除月份
                st.subheader("🗑️ 刪除月份資料")
                if not df_pay.empty:
                    all_months = sorted(df_pay['月份'].unique().tolist(), reverse=True)
                    del_month = st.selectbox("選擇要刪除的月份", all_months, key="del_select")
                    st.warning(f"警告：刪除 {del_month} 後將無法復原。")
                    confirm_del = st.checkbox(f"我確認要刪除 {del_month} 的所有薪資紀錄")
                    if st.button("🔥 執行刪除", type="secondary") and confirm_del:
                        # 排除掉該月份的資料
                        df_remaining = df_pay[df_pay['月份'] != del_month]
                        conn.update(worksheet=PAY_SHEET, data=df_remaining)
                        st.cache_data.clear(); st.success(f"🗑️ {del_month} 資料已刪除"); st.rerun()
                else:
                    st.write("目前無可刪除的月份。")

        # --- 薪資編輯與計算 ---
        target_m = st.sidebar.selectbox("月份切換", sorted(df_pay['月份'].unique().tolist(), reverse=True) if not df_pay.empty else ["無資料"])
        
        if target_m != "無資料":
            curr = df_pay[df_pay['月份'] == target_m].copy()
            if role == 3: curr = curr[curr['店別'] == shop]

            # 核心計算 (含勞健保歷史溯源)
            df_s = df_ins[df_ins['月份'] <= target_m].sort_values(['姓名', '月份'], ascending=[True, False])
            l_ins = df_s.drop_duplicates('姓名')[['姓名', '勞健保自負額']]
            curr = curr.merge(df_emp[['姓名','單位','基本薪資合計','執照津貼','車資補貼']], on='姓名', how='left')
            curr = curr.merge(l_ins, on='姓名', how='left')
            
            num_cols = ALL_VAR_COLS + ['基本薪資合計', '執照津貼', '車資補貼', '勞健保自負額']
            for c in num_cols: curr[c] = pd.to_numeric(curr[c], errors='coerce').fillna(0)
            curr['應付金額'] = (curr['基本薪資合計'] + curr['執照津貼'] + curr['車資補貼'] + curr[ALL_VAR_COLS].sum(axis=1)) - curr['勞健保自負額']

            st.subheader(f"📅 {target_m} 薪資編輯")
            
            unit_filter = st.radio("篩選單位顯示", ["全部", "藥局", "個管師"], horizontal=True)
            display_df = curr.copy()
            if unit_filter != "全部":
                display_df = display_df[display_df['單位'] == unit_filter]
                active_vars = PHARMACY_VAR if unit_filter == "藥局" else CASE_MGR_VAR
                base_info = ["基本薪資合計"] if unit_filter == "藥局" else ["基本薪資合計", "執照津貼", "車資補貼"]
                cols = ["月份", "店別", "姓名"] + base_info + active_vars + ["勞健保自負額", "應付金額", "備註"]
                if role != 1: cols = ["月份", "店別", "姓名"] + active_vars + ["備註"]
                display_df = display_df[[c for c in cols if c in display_df.columns]]

            edited = st.data_editor(display_df, key="main_editor", num_rows="dynamic")

            if st.button("💾 同步薪資存檔"):
                save_cols = ["月份", "店別", "姓名", "備註"] + ALL_VAR_COLS
                save_df = edited[[c for c in save_cols if c in edited.columns]]
                others = df_pay[~((df_pay['月份']==target_m) & (df_pay['姓名'].isin(edited['姓名'])))]
                conn.update(worksheet=PAY_SHEET, data=pd.concat([others, save_df], ignore_index=True)); st.cache_data.clear(); st.success("已存檔")

            if role == 1:
                st.markdown("---")
                c1, c2 = st.columns(2)
                with c1:
                    df_ph = curr[curr['單位'] == '藥局']
                    if not df_ph.empty: st.download_button("📥 下載【藥局】網銀檔", generate_bank_csv(df_ph, df_emp, target_m), f"Pharmacy_{target_m}.csv", use_container_width=True)
                with c2:
                    df_cm = curr[curr['單位'] == '個管師']
                    if not df_cm.empty: st.download_button("📥 下載【個管師】網銀檔", generate_bank_csv(df_cm, df_emp, target_m), f"CaseManager_{target_m}.csv", use_container_width=True)

    with tabs[1]: # 員工資料
        if role == 1:
            e_emp = st.data_editor(df_emp, num_rows="dynamic")
            if st.button("💾 更新員工資料庫"): conn.update(worksheet=EMP_SHEET, data=e_emp); st.cache_data.clear(); st.success("更新成功")

if __name__ == "__main__":
    main()
