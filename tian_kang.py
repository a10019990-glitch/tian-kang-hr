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

def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def robust_clean(df):
    if df is None or df.empty: return pd.DataFrame()
    df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
    mapping = {c: "店別" for c in df.columns if "店別" in c or "店號" in c}
    mapping.update({c: "姓名" for c in df.columns if "姓名" in c})
    mapping.update({c: "月份" for c in df.columns if "月份" in c})
    mapping.update({c: "勞健保自負額" for c in df.columns if "自負額" in c or "勞健保" in c})
    mapping.update({c: "身分證" for c in df.columns if "身分證" in c or "字號" in c})
    df = df.rename(columns=mapping)
    if "店別" in df.columns:
        df["店別"] = df["店別"].apply(lambda x: re.findall(r'\d+', str(x))[0].zfill(2) if re.findall(r'\d+', str(x)) else str(x).strip())
    return df

def main():
    st.title("🚀 天康連鎖藥局 - 雲端管理系統")
    conn = st.connection("gsheets", type=GSheetsConnection)

    if st.sidebar.button("🔄 重新載入資料"):
        st.cache_data.clear()
        st.rerun()

    DEFAULT_TTL = 300 

    try:
        df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl=DEFAULT_TTL))
        df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl=DEFAULT_TTL))
        df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl=DEFAULT_TTL))
        try:
            df_acc = robust_clean(conn.read(worksheet=ACC_SHEET, ttl=DEFAULT_TTL))
        except:
            df_acc = pd.DataFrame(columns=["姓名", "身分證", "帳號", "密碼"])
    except Exception as e:
        st.error("❌ 雲端連線忙碌中，請稍候 30 秒再重新載入。")
        st.stop()

    # --- 登入控制系統 ---
    if 'auth' not in st.session_state:
        mode = st.radio("系統入口", ["員工查詢", "管理端登入", "新員工註冊"], horizontal=True)
        
        if mode == "員工查詢":
            acc = st.text_input("帳號")
            pw = st.text_input("密碼", type="password")
            if st.button("登入查詢"):
                match = df_acc[(df_acc['帳號'] == acc) & (df_acc['密碼'] == hash_password(pw))]
                if not match.empty:
                    st.session_state.auth, st.session_state.user_name = 5, match.iloc[0]['姓名']
                    st.rerun()
                else: st.error("帳號或密碼錯誤")

        elif mode == "管理端登入":
            admin = st.text_input("管理帳號 (boss, mgr_xx, 或 acct)")
            if st.button("進入系統"):
                if admin == "boss":
                    st.session_state.auth, st.session_state.shop = 1, "ALL"
                elif admin == "acct": # 新增會計權限
                    st.session_state.auth, st.session_state.shop = 4, "ACCOUNTING"
                elif admin.startswith("mgr_"):
                    st.session_state.auth, st.session_state.shop = 3, re.findall(r'\d+', admin)[0].zfill(2)
                else: st.error("權限不足")
                st.rerun()

        elif mode == "新員工註冊":
            with st.form("reg_form"):
                reg_name = st.text_input("姓名")
                reg_id = st.text_input("身分證字號")
                reg_acc = st.text_input("設定帳號")
                reg_pw = st.text_input("設定密碼", type="password")
                if st.form_submit_button("完成註冊"):
                    if not df_emp[(df_emp['姓名']==reg_name) & (df_emp['身分證']==reg_id)].empty:
                        new_u = pd.DataFrame({"姓名":[reg_name], "身分證":[reg_id], "帳號":[reg_acc], "密碼":[hash_password(reg_pw)]})
                        conn.update(worksheet=ACC_SHEET, data=pd.concat([df_acc, new_u], ignore_index=True))
                        st.cache_data.clear(); st.success("註冊成功！")
                    else: st.error("資料不符")
        return

    # --- 權限分流邏輯 ---
    role = st.session_state.auth
    
    # 員工 (Role 5)
    if role == 5:
        name = st.session_state.user_name
        st.subheader(f"👋 {name}，個人薪資明細")
        p_pay = df_pay[df_pay['姓名'] == name].copy()
        p_pay = p_pay.merge(df_emp[['姓名','基本薪資合計']], on='姓名', how='left')
        p_pay = p_pay.merge(df_ins[['姓名','勞健保自負額']], on='姓名', how='left')
        bonus_list = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
        for c in bonus_list + ['基本薪資合計', '勞健保自負額']: p_pay[c] = pd.to_numeric(p_pay[c], errors='coerce').fillna(0)
        p_pay['實領金額'] = (p_pay['基本薪資合計'] + p_pay[bonus_list].sum(axis=1)) - p_pay['勞健保自負額']
        st.dataframe(p_pay[["月份", "店別", "基本薪資合計"] + bonus_list + ["勞健保自負額", "實領金額", "備註"]])
        if st.sidebar.button("登出"): del st.session_state['auth']; st.rerun()

    # 管理端 (Role 1:老闆, 3:店長, 4:會計)
    else:
        shop = st.session_state.shop
        st.sidebar.success(f"📍 權限：{shop}")
        if st.sidebar.button("登出系統"): del st.session_state['auth']; st.rerun()

        # 會計權限過濾：只能看到員工資料跟勞健保
        if role == 4:
            all_tabs = ["👤 員工名單對照", "🏥 勞健保資料同步"]
            tabs = st.tabs(all_tabs)
            
            with tabs[0]:
                st.subheader("👤 員工清單 (唯讀對照用)")
                st.dataframe(df_emp[["店別", "姓名"]])
                
            with tabs[1]:
                st.subheader("🏥 勞健保明細管理 (會計編輯區)")
                edited_ins = st.data_editor(df_ins, num_rows="dynamic", key="acct_ins")
                if st.button("💾 同步更新勞健保至雲端"):
                    conn.update(worksheet=INS_SHEET, data=edited_ins)
                    st.cache_data.clear(); st.success("會計資料已同步更新！")
        
        else: # 老闆與店長功能
            tabs = st.tabs(["💰 薪資發薪", "👤 員工資料", "🏥 勞健保資料", "🔑 帳號清單"])
            with tabs[0]: # 薪資與匯出 (維持原有老闆/店長邏輯)
                if role == 1:
                    with st.sidebar.expander("➕ [管理] 建立新月份"):
                        nm = st.text_input("新月份", "2026-04")
                        if st.button("寫入雲端"):
                            new_r = pd.DataFrame({"月份":[nm]*len(df_emp), "店別":df_emp["店別"], "姓名":df_emp["姓名"], "職務加給":0, "加班津貼":0, "店毛利成長獎金":0, "推廣獎金":0, "輔具推廣獎金":0, "慢籤成長獎金":0, "備註":""})
                            conn.update(worksheet=PAY_SHEET, data=pd.concat([df_pay, new_r], ignore_index=True)); st.cache_data.clear(); st.rerun()

                target_m = st.sidebar.selectbox("月份", sorted(df_pay['月份'].unique().tolist(), reverse=True))
                mask = (df_pay['月份'] == target_m)
                if role == 3: mask = mask & (df_pay['店別'] == shop)
                curr = df_pay[mask].copy()
                if role == 1:
                    curr = curr.merge(df_emp[['姓名','基本薪資合計']], on='姓名', how='left')
                    curr = curr.merge(df_ins[['姓名','勞健保自負額']], on='姓名', how='left')
                    bonus = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
                    for c in bonus + ['基本薪資合計', '勞健保自負額']: curr[c] = pd.to_numeric(curr[c], errors='coerce').fillna(0)
                    curr['應付金額'] = (curr['基本薪資合計'] + curr[bonus].sum(axis=1)) - curr['勞健保自負額']

                edited = st.data_editor(curr, key="boss_pay")
                if st.button("💾 同步薪資存檔"):
                    save_df = edited[["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]]
                    others = df_pay[~((df_pay['月份']==target_m) & (df_pay['店別'] == (shop if role==3 else df_pay['店別'])))]
                    conn.update(worksheet=PAY_SHEET, data=pd.concat([others, save_df], ignore_index=True)); st.cache_data.clear(); st.success("薪資已更新")

                if role == 1: # 老闆匯出銀行檔
                    if st.button("🚀 匯出網銀 CSV"):
                        f_df = edited.merge(df_emp[['姓名', '身分證', '收款帳號']], on='姓名', how='left')
                        bank = pd.DataFrame({"日期":datetime.now().strftime("%Y%m%d"),"項目":"901","編號":"75440263","姓名":f_df["姓名"],"身分證":f_df["身分證"],"帳號":f_df["收款帳號"],"金額":f_df["應付金額"],"附言":"薪資","性質":"02"})
                        st.download_button("📥 下載", bank.to_csv(index=False).encode('utf-8-sig'), f"Bank_{target_m}.csv")

            with tabs[1]: # 員工資料
                if role == 1:
                    e_emp = st.data_editor(df_emp, num_rows="dynamic")
                    if st.button("💾 更新員工主表"): conn.update(worksheet=EMP_SHEET, data=e_emp); st.cache_data.clear(); st.success("更新成功")
                else: st.dataframe(df_emp[df_emp['店別'] == shop])
            
            with tabs[2]: # 勞健保資料 (老闆/店長版)
                if role == 1:
                    e_ins = st.data_editor(df_ins, num_rows="dynamic")
                    if st.button("💾 更新勞健保表"): conn.update(worksheet=INS_SHEET, data=e_ins); st.cache_data.clear(); st.success("更新成功")
                else: st.dataframe(df_ins[df_ins['姓名'].isin(df_emp[df_emp['店別']==shop]['姓名'])])

            with tabs[3]: # 帳號管理
                st.dataframe(df_acc)

if __name__ == "__main__":
    main()
