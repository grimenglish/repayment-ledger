"""Public-domain passages; Korean wording is our own translation."""
from html import escape
from random import choice
import streamlit as st

FRANKLIN='https://www.gutenberg.org/cache/epub/36151/pg36151-images.html'
MARCUS='https://www.gutenberg.org/files/6920/6920-h/6920-h.htm'
QUOTES=(
    ('잘하는 행동이 잘하는 말보다 낫다.','벤자민 프랭클린','Well done is better than well said.','Poor Richard’s Almanac',FRANKLIN),
    ('부지런함은 행운의 어머니다.','벤자민 프랭클린','Diligence is the mother of good luck.','The Way to Wealth',FRANKLIN),
    ('작은 도끼질이 큰 참나무를 쓰러뜨린다.','벤자민 프랭클린','Little strokes fell great oaks.','The Way to Wealth',FRANKLIN),
    ('끊임없이 떨어지는 물방울은 돌을 닳게 한다.','벤자민 프랭클린','Constant dropping wears away stones.','The Way to Wealth',FRANKLIN),
    ('오늘 할 수 있는 일을 내일로 미루지 마라.','벤자민 프랭클린','Never leave that till to-morrow which you can do to-day.','The Way to Wealth',FRANKLIN),
    ('버는 것보다 적게 쓰는 법을 알면, 부를 만드는 비결을 가진 것이다.','벤자민 프랭클린','If you know how to spend less than you get, you have the philosopher’s stone.','Poor Richard’s Almanac',FRANKLIN),
    ('어떤 사람이 좋은 사람인지 말하기보다, 그런 사람이 되어라.','마르쿠스 아우렐리우스','No longer talk at all about the kind of man that a good man ought to be, but be such.','Meditations X.16',MARCUS),
)

def choose_quote(previous=None):
    return choice([i for i in range(len(QUOTES)) if i!=previous])

def render_header():
    if 'header_quote' not in st.session_state:
        st.session_state['header_quote']=choose_quote()
    quote,author,original,work,source=QUOTES[st.session_state['header_quote']]
    title,words=st.columns([5,7],vertical_alignment='center')
    with title:
        st.title('우리집 상환장부')
    with words:
        st.markdown('<div style="border-left:3px solid #2563eb;padding:8px 16px;margin-bottom:8px">'
                    f'<div style="font-size:1.08rem;font-weight:650;line-height:1.6">“{escape(quote)}”</div>'
                    f'<a href="{escape(source,quote=True)}" target="_blank" rel="noopener noreferrer" style="font-size:.85rem;color:#526177">— {escape(author)}</a></div>',unsafe_allow_html=True)
        def rotate():
            st.session_state['header_quote']=choose_quote(st.session_state['header_quote'])
        st.button('다른 명언 ↻',key='rotate_header_quote',on_click=rotate,help='입력 중에는 명언이 유지됩니다. 누르면 다른 명언을 보여줍니다.')
        with st.expander('명언 출처'):
            st.caption('한국어 문구는 원문을 직접 번역했습니다.')
            st.write(original)
            st.markdown(f'[{author} · {work}]({source})')
