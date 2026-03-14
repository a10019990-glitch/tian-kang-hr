import streamlit as st
import pandas as pd

# --- 設定區 ---
SHEET_ID = "1DPOtSzamSDEbSZLkhpGNuTsBk-mqbsYHY6cGnHQDDOc"
SHEET_NAME = "salary_data" # 請確認 Google Sheet 下方分頁標籤真的是這個英文名字
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME}"

st.set_page_config(page_title="天康藥局診斷系統", layout="wide")

def main():
    st.title("🔍 天康藥局 - 欄位診斷工具")
    
    # 讀取資料
    try:
        # 強制指定用 UTF-8 編號讀取，避開亂碼
        all_df = pd.read_csv(CSV_URL, encoding='utf-8')
        all_df = all_df.dropna(how='all', axis=0)
    except Exception as e:
        st.error(f"❌ 連網址都連不上：{e}")
        return

    # --- 關鍵診斷區 ---
    st.subheader("📋 電腦目前看到的欄位標題：")
    actual_columns = list(all_df.columns)
    st.write(actual_columns) # 這行會把所有欄位名字印在網頁上

    # 檢查是否有任何一欄包含「月份」兩個字 (防空格、防亂碼)
    found_month_col = [c for c in actual_columns if "月份" in str(c)]
    
    if not found_month_col:
        st.error("🚨 警告：真的完全找不到包含『月份』的欄位！")
        st.info("💡 請檢查您的 Google Sheet 第一行（Row 1），『月份』這兩個字是不是在第一格？")
        st.write("這是電腦抓到的前 5 行資料，讓你核對：")
        st.table(all_df.head(5)) # 把前幾行資料秀出來
        return
    else:
        # 如果找到了（可能是因為有空格），我們幫它強制正名
        target_col = found_month_col[0]
        all_df = all_df.rename(columns={target_col: "月份"})
        st.success(f"✅ 找到欄位了！原始名稱為：'{target_col}'，已自動修正。")

    # --- 接下來是原本的登入與顯示邏輯 ---
    if 'auth' not in st.session_state:
        user = st.text_input("帳號 (例如: boss)")
        if st.button("登入"):
            if user == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
            st.rerun()
        return

    target_month = st.selectbox("選擇月份", ["2026-02", "2026-03"])
    all_df['月份'] = all_df['月份'].astype(str)
    mask = (all_df['月份'].str.contains(target_month))
    st.dataframe(all_df[mask])

if __name__ == "__main__":
    main()
