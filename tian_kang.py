import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import re
import hashlib

# --- 1. 雲端設定 ---
SHEET_ID = "1TcrNfnSKj7hMd0LOXipBD9eKAft6yU7YnhZNX6rtPhg"
PAY_SHEET = "salary_data"
EMP_SHEET = "emp_info"
INS_SHEET = "ins_info"
ACC_SHEET = "user_accounts"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# --- 2. 核心工具 ---
def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def robust_clean(df, expected_cols=None):
    if df is None or df.empty: return pd.DataFrame(columns=expected_cols if expected_cols else [])
    df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
    
    # 💡 修正映射邏輯：保留「月份」與「生效月份」的獨立性
    mapping = {
        "月份": "月份", 
        "生效月份": "生效月份", 
        "姓名": "姓名", "身分證": "身分證",
        "勞保": "勞保", "健保": "健保", "健保人數": "健保人數",
        "勞健保個人負擔": "勞健保個人負擔", "加保日期": "加保日期",
        "單位": "單位", "店別": "店別", "基本薪資合計": "基本薪資合計",
        "執照津貼": "執照津貼", "車資補貼": "車資補貼", "備註": "備註", "收款帳號": "收款帳號"
    }
    
    new_mapping = {}
    for c in df.columns:
        for k, v in mapping.items():
            if k in c: new_mapping[c] = v
            
    df = df.rename(columns=new_mapping)
    if expected_cols:
        for col in expected_cols:
            if col not in df.columns: 
                df[col] = 0 if any(x in col for x in ["獎金", "津貼", "合計", "補貼", "訪", "負擔", "勞保", "健保", "人數"]) else ""
    
    # 強力去重與格式清洗
    df = df.loc[:, ~df.columns.duplicated()]
    if "單位" in df.columns: df["單位"] = df["單位"].astype(str).str.strip()
    if "店別" in df.columns:
        df["店別"] = df["店別"].apply(lambda x: re.findall(r'\d+', str(x))[0].zfill(2) if re.findall(r'\d+', str(x)) else str(x).strip())
    return df

def generate_bank_csv(df_source, df_employee, target_m):
    emp_sub = df_employee[['姓名', '身分證', '收款帳號']].drop_duplicates('姓名')
    f_df = df_source.merge(emp_sub, on='姓名', how='left')
    bank = pd.DataFrame({
        "付款日期": datetime.now().strftime("%Y%m%d"), "轉帳項目": "901", "企業編號": "75440263",
        "員工姓名": f_df["姓名"], "身分證字號": f_df["身分證"], "收款帳號": f_df["收款帳號"],
        "交易金額": f_df["應付金額"], "附言": "薪資", "付款性質": "02"
    })
    return bank.to_csv(index=False).encode('utf-8-sig')

def main():
    st.title("🚀 天康連鎖藥局 - 雙單位發薪管理系統")
    conn = st.connection("gsheets", type=GSheetsConnection)

    if st.sidebar.button("🔄 刷新雲端資料"):
        st.cache_data.clear(); st.rerun()

    # --- 定義欄位結構 ---
    PHARMACY_VAR = ['職務加給', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金', '加班津貼']
    CASE_MGR_VAR = ['電訪', '超額電訪', '家訪', '超額家訪', '三節獎金', '輔具獎金', '加班津貼']
    ALL_VAR_COLS = list(set(PHARMACY_VAR + CASE_MGR_VAR))
    # 會計要求的 8 個欄位
    INS_COLS = ['生效月份', '姓名', '身分證', '勞保', '健保', '健保人數', '勞健保個人負擔', '加保日期']

    # --- 3. 讀取資料 ---
    try:
        df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl=300), expected_cols=['姓名', '單位', '店別', '身分證', '收款帳號', '基本薪資合計', '執照津貼', '車資補貼'])
        df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl=300), expected_cols=['月份', '店別', '姓名', '備註'] + ALL_VAR_COLS)
        df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl=300), expected_cols=INS_COLS)
        df_acc = robust_clean(conn.read(worksheet=ACC_SHEET, ttl=300))
    except Exception as e:
        st.error(f"❌ 雲端讀取失敗: {e}"); st.stop()

    # --- 4. 登入系統 ---
    if 'auth' not in st.session_state:
        mode = st.radio("入口選擇", ["管理端登入", "員工薪資查詢", "新帳號註冊"], horizontal=True)
        if mode == "管理端登入":
            acc = st.text_input("管理帳號"); pw = st.text_input("管理密碼", type="password")
            if st.button("登入後台"):
                match = df_acc[(df_acc['帳號'] == acc) & (df_acc['密碼'] == hash_password(pw))]
                if not match.empty:
                    if acc == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
                    elif acc == "acct": st.session_state.auth, st.session_state.shop = 4, "ACCOUNTING"
                    elif acc.startswith("mgr_"): st.session_state.auth, st.session_state.shop = 3, re.findall(r'\d+', acc)[0].zfill(2)
                    st.rerun()
                else: st.error("❌ 帳密錯誤")
        elif mode == "員工薪資查詢":
            e_acc = st.text_input("員工帳號"); e_pw = st.text_input("員工密碼", type="password")
            if st.button("登入"):
                match = df_acc[(df_acc['帳號'] == e_acc) & (df_acc['密碼'] == hash_password(e_pw))]
                if not match.empty:
                    st.session_state.auth, st.session_state.user_name, st.session_state.shop = 5, match.iloc[0]['姓名'], "PERSONAL"
                    st.rerun()
        elif mode == "新帳號註冊":
            with st.form("reg"):
                n, i, a, p = st.text_input("姓名"), st.text_input("身分證"), st.text_input("帳號"), st.text_input("密碼", type="password")
                if st.form_submit_button("註冊"):
                    if a in ["boss", "acct"] or a.startswith("mgr_") or not df_emp[(df_emp['姓名']==n) & (df_emp['身分證']==i)].empty:
                        new_u = pd.DataFrame({"姓名":[n], "身分證":[i], "帳號":[a], "密碼":[hash_password(p)]})
                        conn.update(worksheet=ACC_SHEET, data=pd.concat([df_acc, new_u], ignore_index=True))
                        st.cache_data.clear(); st.success("註冊成功")
        return

    # --- 5. 權限分流 ---
    role, shop = st.session_state.auth, st.session_state.shop

    if role == 5: # 員工專區
        st.subheader(f"👋 {st.session_state.user_name}，個人薪資明細")
        st.dataframe(df_pay[df_pay['姓名'] == st.session_state.user_name])
        if st.sidebar.button("登出"): del st.session_state['auth']; st.rerun()
    else:
        st.sidebar.success(f"📍 權限：{shop}")
        if st.sidebar.button("登出系統"): del st.session_state['auth']; st.rerun()

        # 會計 (Role 4) - 專屬 8 欄位
        if role == 4:
            t_acct = st.tabs(["🏥 勞健保明細維護", "👤 全體員工名單"])
            with t_acct[0]:
                e_ins = st.data_editor(df_ins[INS_COLS], num_rows="dynamic", key="acct_edit")
                if st.button("💾 同步更新勞健保資料"):
                    conn.update(worksheet=INS_SHEET, data=e_ins); st.cache_data.clear(); st.success("已更新")
            with t_acct[1]:
                st.dataframe(df_emp[["店別", "姓名", "單位", "身分證"]].sort_values("店別"))

        else: # 老闆 (1) 與 店長 (3)
            tabs = st.tabs(["💰 薪資發薪作業", "👤 員工資料庫", "🏥 勞健保紀錄檢視", "🔑 帳號管理"])
            
            with tabs[0]: # 薪資作業
                if role == 1:
                    with st.sidebar.expander("🛠️ 月份名單管理"):
                        nm = st.text_input("建立新月份", "2026-05")
                        if st.button("執行建立"):
                            latest_rem = df_pay.sort_values(['姓名','月份'], ascending=[True,False]).drop_duplicates('姓名')[['姓名','備註']] if not df_pay.empty else pd.DataFrame(columns=['姓名','備註'])
                            df_t = df_emp[['姓名']].merge(latest_rem, on='姓名', how='left')
                            new_r = pd.DataFrame({"月份":[nm]*len(df_emp), "店別":df_emp["店別"], "姓名":df_emp["姓名"], "備註":df_t["備註"].fillna("").tolist()})
                            for c in ALL_VAR_COLS: new_r[c] = 0
                            conn.update(worksheet=PAY_SHEET, data=pd.concat([df_pay, new_r], ignore_index=True)); st.cache_data.clear(); st.rerun()
                        all_m = sorted(df_pay['月份'].unique().tolist(), reverse=True) if not df_pay.empty else []
                        if all_m:
                            st.markdown("---")
                            del_m = st.selectbox("刪除月份", all_m)
                            if st.button("🔥 刪除") and st.checkbox(f"我確認要刪除 {del_m}"):
                                conn.update(worksheet=PAY_SHEET, data=df_pay[df_pay['月份'] != del_m]); st.cache_data.clear(); st.rerun()

                target_m = st.sidebar.selectbox("月份切換", sorted(df_pay['月份'].unique().tolist(), reverse=True) if not df_pay.empty else ["無"])
                if target_m != "無":
                    # 計算邏輯：用「月份」去對應勞健保表的「生效月份」
                    df_s = df_ins[df_ins['生效月份'] <= target_m].sort_values(['姓名', '生效月份'], ascending=[True, False])
                    l_ins = df_s.drop_duplicates('姓名')[['姓名', '勞健保個人負擔']]
                    curr = df_pay[df_pay['月份'] == target_m].copy()
                    if role == 3: curr = curr[curr['店別'] == shop]
                    
                    emp_info = df_emp[['姓名','單位','基本薪資合計','執照津貼','車資補貼']].drop_duplicates('姓名')
                    curr = curr.merge(emp_info, on='姓名', how='left', suffixes=('', '_dup'))
                    curr = curr.merge(l_ins, on='姓名', how='left', suffixes=('', '_dup'))
                    curr = curr.loc[:, ~curr.columns.duplicated()] 
                    
                    for c in ALL_VAR_COLS + ['基本薪資合計', '執照津貼', '車資補貼', '勞健保個人負擔']: curr[c] = pd.to_numeric(curr[c], errors='coerce').fillna(0)
                    curr['應付金額'] = (curr['基本薪資合計'] + curr['執照津貼'] + curr['車資補貼'] + curr[ALL_VAR_COLS].sum(axis=1)) - curr['勞健保個人負擔']

                    unit_f = st.radio("篩選顯示", ["全部", "藥局", "個管師"], horizontal=True)
                    display_df = curr.copy()
                    if unit_f != "全部":
                        display_df = display_df[display_df['單位'] == unit_f]
                        active_vars = PHARMACY_VAR if unit_f == "藥局" else CASE_MGR_VAR
                        base_info = ["基本薪資合計"] if unit_f == "藥局" else ["基本薪資合計", "執照津貼", "車資補貼"]
                        cols = ["月份", "店別", "姓名"] + base_info + active_vars + ["勞健保個人負擔", "應付金額", "備註"]
                        if role != 1: cols = ["月份", "店別", "姓名"] + active_vars + ["備註"]
                        display_df = display_df[[c for c in cols if c in display_df.columns]]

                    display_df = display_df.loc[:, ~display_df.columns.duplicated()]
                    edited = st.data_editor(display_df, key="main_edit", num_rows="dynamic")
                    
                    if st.button("💾 同步存檔"):
                        save_cols = ["月份", "店別", "姓名", "備註"] + ALL_VAR_COLS
                        save_df = edited[[c for c in save_cols if c in edited.columns]]
                        others = df_pay[~((df_pay['月份']==target_m) & (df_pay['姓名'].isin(edited['姓名'])))]
                        conn.update(worksheet=PAY_SHEET, data=pd.concat([others, save_df], ignore_index=True)); st.cache_data.clear(); st.success("存檔成功")

                    if role == 1:
                        st.markdown("---")
                        c1, c2 = st.columns(2)
                        with c1:
                            df_ph = curr[curr['單位'] == '藥局']
                            if not df_ph.empty: st.download_button("📥 【藥局】網銀檔", generate_bank_csv(df_ph, df_emp, target_m), f"Pharmacy_{target_m}.csv")
                        with c2:
                            df_cm = curr[curr['單位'] == '個管師']
                            if not df_cm.empty: st.download_button("📥 【個管師】網銀檔", generate_bank_csv(df_cm, df_emp, target_m), f"CaseManager_{target_m}.csv")

            with tabs[1]: # 員工資料
                if role == 1:
                    e_emp = st.data_editor(df_emp, num_rows="dynamic")
                    if st.button("💾 更新員工資料"): conn.update(worksheet=EMP_SHEET, data=e_emp); st.cache_data.clear()
                else: st.dataframe(df_emp[df_emp['店別'] == shop])

            with tabs[2]: # 勞健保紀錄檢視
                st.dataframe(df_ins[INS_COLS].sort_values(['姓名', '生效月份'], ascending=[True, False]))

            with tabs[3]: # 帳號管理
                st.dataframe(df_acc[["姓名", "帳號", "身分證"]])

if __name__ == "__main__":
    main()
