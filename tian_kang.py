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
    mapping = {
        "月份": "月份", "生效月份": "生效月份", "姓名": "姓名", "身分證": "身分證",
        "勞保": "勞保", "健保": "健保", "健保人數": "健保人數",
        "勞健保個人負擔": "勞健保個人負擔", "加保日期": "加保日期",
        "單位": "單位", "店別": "店別", "基本薪資合計": "基本薪資合計",
        "執照津貼": "執照津貼", "車資補貼": "車資補貼", "備註": "備註", "收款帳號": "收款帳號"
    }
    new_mapping = {c: mapping[k] for c in df.columns for k in mapping if k in c}
    df = df.rename(columns=new_mapping)
    if expected_cols:
        for col in expected_cols:
            if col not in df.columns: 
                df[col] = 0 if any(x in col for x in ["獎金", "津貼", "合計", "補貼", "訪", "負擔", "勞保", "健保", "人數"]) else ""
    return df.loc[:, ~df.columns.duplicated()]

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

    # --- 欄位結構定義 ---
    PHARMACY_VAR = ['職務加給', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金', '加班津貼']
    CASE_MGR_VAR = ['電訪', '超額電訪', '家訪', '超額家訪', '三節獎金', '輔具獎金', '加班津貼']
    ALL_VAR_COLS = list(set(PHARMACY_VAR + CASE_MGR_VAR))
    INS_COLS = ['生效月份', '姓名', '身分證', '勞保', '健保', '健保人數', '勞健保個人負擔', '加保日期']

    # --- 3. 讀取資料 ---
    try:
        df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl=300), expected_cols=['姓名', '單位', '店別', '身分證', '收款帳號', '基本薪資合計', '執照津貼', '車資補貼'])
        df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl=300), expected_cols=['月份', '店別', '姓名', '備註'] + ALL_VAR_COLS)
        df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl=300), expected_cols=INS_COLS)
        df_acc = robust_clean(conn.read(worksheet=ACC_SHEET, ttl=300))
    except Exception as e:
        st.error(f"❌ 雲端連線失敗: {e}"); st.stop()

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

    role, shop = st.session_state.auth, st.session_state.shop

    # --- 5. 權限分流 ---
    if role == 5: # 【核心優化：員工專區】
        name = st.session_state.user_name
        st.subheader(f"👋 {name}，個人薪資明細查詢")
        
        # 1. 抓取員工單位資訊
        emp_info = df_emp[df_emp['姓名'] == name].iloc[0] if not df_emp[df_emp['姓名'] == name].empty else None
        
        if emp_info is not None:
            unit = str(emp_info['單位']).strip()
            # 2. 篩選該員工的發薪紀錄
            p_pay = df_pay[df_pay['姓名'] == name].copy()
            
            # 3. 合併勞健保與本薪計算
            df_s = df_ins[df_ins['姓名'] == name].sort_values(['生效月份'], ascending=False)
            p_pay = p_pay.merge(df_s[['生效月份', '勞健保個人負擔']], left_on='月份', right_on='生效月份', how='left')
            
            # 4. 計算總金額
            p_pay['基本薪資合計'] = emp_info['基本薪資合計']
            p_pay['執照津貼'] = emp_info['執照津貼']
            p_pay['車資補貼'] = emp_info['車資補貼']
            
            for c in ALL_VAR_COLS + ['勞健保個人負擔']:
                p_pay[c] = pd.to_numeric(p_pay[c], errors='coerce').fillna(0)
            
            # 計算邏輯：本薪 + 津貼 + 該單位獎金 - 勞健保
            bonus_cols = PHARMACY_VAR if unit == "藥局" else CASE_MGR_VAR
            base_total = p_pay['基本薪資合計'] + p_pay['執照津貼'] + p_pay['車資補貼']
            p_pay['實領總額'] = (base_total + p_pay[bonus_cols].sum(axis=1)) - p_pay['勞健保個人負擔']
            
            # 5. 根據單位顯示不同欄位
            if unit == "藥局":
                show_cols = ['月份', '店別', '姓名', '基本薪資合計'] + PHARMACY_VAR + ['勞健保個人負擔', '實領總額', '備註']
            else: # 個管師
                show_cols = ['月份', '姓名', '基本薪資合計', '執照津貼', '車資補貼'] + CASE_MGR_VAR + ['勞健保個人負擔', '實領總額', '備註']
            
            st.dataframe(p_pay[[c for c in show_cols if c in p_pay.columns]])
        else:
            st.error("❌ 系統找不到您的員工資料，請聯繫大助。")
        
        if st.sidebar.button("登出"): del st.session_state['auth']; st.rerun()

    else: # 管理端 (老闆/店長/會計)
        st.sidebar.success(f"📍 權限：{shop}")
        if st.sidebar.button("登出系統"): del st.session_state['auth']; st.rerun()

        if role == 4: # 會計 (維持 8 欄位)
            t_acct = st.tabs(["🏥 勞健保明細維護", "👤 全體員工名單"])
            with t_acct[0]:
                e_ins = st.data_editor(df_ins[INS_COLS], num_rows="dynamic", key="acct_edit")
                if st.button("💾 同步更新勞健保資料"):
                    conn.update(worksheet=INS_SHEET, data=e_ins); st.cache_data.clear(); st.success("已更新")
            with t_acct[1]:
                st.dataframe(df_emp[["店別", "姓名", "單位", "身分證"]].sort_values("店別"))

        else: # 老闆 (Role 1) 與 店長 (Role 3)
            tabs = st.tabs(["💰 薪資發薪作業", "👤 員工資料庫", "🏥 勞健保紀錄檢視", "🔑 帳號管理"])
            
            with tabs[0]: # 薪資作業
                if role == 1:
                    with st.sidebar.expander("🛠️ 月份名單管理"):
                        nm = st.text_input("建立新月份", "2026-06")
                        if st.button("執行建立"):
                            latest_rem = df_pay.sort_values(['姓名','月份'], ascending=[True,False]).drop_duplicates('姓名')[['姓名','備註']] if not df_pay.empty else pd.DataFrame(columns=['姓名','備註'])
                            df_t = df_emp[['姓名']].merge(latest_rem, on='姓名', how='left')
                            new_r = pd.DataFrame({"月份":[nm]*len(df_emp), "店別":df_emp["店別"], "姓名":df_emp["姓名"], "備註":df_t["備註"].fillna("").tolist()})
                            for c in ALL_VAR_COLS: new_r[c] = 0
                            conn.update(worksheet=PAY_SHEET, data=pd.concat([df_pay, new_r], ignore_index=True)); st.cache_data.clear(); st.success(f"{nm} 已建立"); st.rerun()
                        
                        st.markdown("---")
                        # 刪除功能 (維持外部勾選框邏輯)
                        all_m_raw = df_pay['月份'].dropna().unique().tolist()
                        all_m_safe = sorted([str(m) for m in all_m_raw if str(m).strip() != ""], reverse=True)
                        if all_m_safe:
                            del_m = st.selectbox("選擇刪除月份", all_m_safe, key="del_selector")
                            conf_del = st.checkbox(f"我確認要刪除 {del_m}", key="conf_check")
                            if st.button("🔥 執行永久刪除", disabled=not conf_del):
                                conn.update(worksheet=PAY_SHEET, data=df_pay[df_pay['月份'].astype(str) != del_m])
                                st.cache_data.clear(); st.rerun()

                # 薪資編輯與匯出邏輯 (不刪減)
                target_m = st.sidebar.selectbox("月份切換", sorted([str(m) for m in df_pay['月份'].dropna().unique()], reverse=True) if not df_pay.empty else ["無"], key="target_box")
                if target_m != "無":
                    df_s = df_ins[df_ins['生效月份'].astype(str) <= target_m].sort_values(['姓名', '生效月份'], ascending=[True, False])
                    l_ins = df_s.drop_duplicates('姓名')[['姓名', '勞健保個人負擔']]
                    curr = df_pay[df_pay['月份'].astype(str) == target_m].copy()
                    if role == 3: curr = curr[curr['店別'] == shop]
                    
                    curr = curr.merge(df_emp[['姓名','單位','基本薪資合計','執照津貼','車資補貼']], on='姓名', how='left')
                    curr = curr.merge(l_ins, on='姓名', how='left')
                    curr = curr.loc[:, ~curr.columns.duplicated()] 
                    
                    for c in ALL_VAR_COLS + ['基本薪資合計', '執照津貼', '車資補貼', '勞健保個人負擔']: curr[c] = pd.to_numeric(curr[c], errors='coerce').fillna(0)
                    curr['應付金額'] = (curr['基本薪資合計'] + curr['執照津貼'] + curr['車資補貼'] + curr[ALL_VAR_COLS].sum(axis=1)) - curr['勞健保個人負擔']

                    st.subheader(f"📅 {target_m} 薪資核對區")
                    unit_f = st.radio("篩選顯示", ["全部", "藥局", "個管師"], horizontal=True)
                    display_df = curr.copy()
                    if unit_f != "全部":
                        display_df = display_df[display_df['單位'] == unit_f]
                        active_vars = PHARMACY_VAR if unit_f == "藥局" else CASE_MGR_VAR
                        base_info = ["基本薪資合計"] if unit_f == "藥局" else ["基本薪資合計", "執照津貼", "車資補貼"]
                        cols = ["月份", "店別", "姓名"] + base_info + active_vars + ["勞健保個人負擔", "應付金額", "備註"]
                        if role != 1: cols = ["月份", "店別", "姓名"] + active_vars + ["備註"]
                        display_df = display_df[[c for c in cols if c in display_df.columns]]

                    edited = st.data_editor(display_df, key="main_edit", num_rows="dynamic")
                    if st.button("💾 同步薪資存檔"):
                        save_cols = ["月份", "店別", "姓名", "備註"] + ALL_VAR_COLS
                        save_df = edited[[c for c in save_cols if c in edited.columns]]
                        others = df_pay[~((df_pay['月份'].astype(str)==target_m) & (df_pay['姓名'].isin(edited['姓名'])))]
                        conn.update(worksheet=PAY_SHEET, data=pd.concat([others, save_df], ignore_index=True)); st.cache_data.clear(); st.success("已存檔")

                    if role == 1:
                        st.markdown("---")
                        c1, c2 = st.columns(2)
                        with c1:
                            df_ph = curr[curr['單位'] == "藥局"]
                            if not df_ph.empty: st.download_button("📥 下載【藥局】網銀檔", generate_bank_csv(df_ph, df_emp, target_m), f"Phar_{target_m}.csv")
                        with c2:
                            df_cm = curr[curr['單位'] == "個管師"]
                            if not df_cm.empty: st.download_button("📥 下載【個管師】網銀檔", generate_bank_csv(df_cm, df_emp, target_m), f"Case_{target_m}.csv")

            with tabs[1]: # 員工資料
                if role == 1:
                    e_emp = st.data_editor(df_emp, num_rows="dynamic")
                    if st.button("💾 更新員工資料庫"): conn.update(worksheet=EMP_SHEET, data=e_emp); st.cache_data.clear()
                else: st.dataframe(df_emp[df_emp['店別'] == shop])

            with tabs[2]: # 勞健保紀錄
                st.dataframe(df_ins[INS_COLS].sort_values(['姓名', '生效月份'], ascending=[True, False]))

            with tabs[3]: # 帳號管理
                st.dataframe(df_acc[["姓名", "帳號", "身分證"]])

if __name__ == "__main__":
    main()
