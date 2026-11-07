# fb-dl

[English](README.md) · **Tiếng Việt**

> [!WARNING]
> **Dự án chỉ dành cho mục đích học tập.** Chỉ tải nội dung bạn được phép xem và lưu.
> Không dùng để đăng lại hoặc bán nội dung của người khác.

Tải **toàn bộ** những gì một trang cá nhân hoặc fanpage Facebook đã đăng, từ bài đầu tiên tới hôm nay,
chất lượng cao nhất, tự phân loại vào từng thư mục:

- **Bài đăng**: nội dung từng bài, kèm link, ngày đăng, số cảm xúc, bình luận, chia sẻ
- **Ảnh** kích thước gốc, kể cả album lớn mà Facebook chỉ hiện vài ảnh đầu
- **Video và reel** chất lượng cao nhất
- **Story** trong 24 giờ qua
- Tab **Ảnh** và **Album**, **avatar** và **ảnh bìa**

Công cụ đọc timeline bằng một cửa sổ trình duyệt ẩn, giống như bạn tự cuộn trang. Đã thử trên một trang
cá nhân có 942 bài, cũ nhất từ năm 2009.

## Mục lục

1. [Bắt đầu nhanh](#bắt-đầu-nhanh)
2. [Cài đặt từng bước](#cài-đặt-từng-bước)
3. [Đăng nhập](#đăng-nhập)
4. [Tải một trang cá nhân hoặc fanpage](#tải-một-trang-cá-nhân-hoặc-fanpage)
5. [Bạn nhận được gì](#bạn-nhận-được-gì)
6. [Dừng, tải tiếp, cập nhật](#dừng-tải-tiếp-cập-nhật)
7. [Tất cả tuỳ chọn](#tất-cả-tuỳ-chọn)
8. [Quyền riêng tư và an toàn](#quyền-riêng-tư-và-an-toàn)
9. [Đăng xuất và xoá dữ liệu](#đăng-xuất-và-xoá-dữ-liệu)
10. [Lỗi thường gặp và câu hỏi](#lỗi-thường-gặp-và-câu-hỏi)

## Bắt đầu nhanh

Đã có Python? Mở cửa sổ lệnh trong thư mục `fb-dl` và chạy:

```bash
pip install -r requirements.txt
python fb-dl.py --login
python fb-dl.py https://www.facebook.com/nasa
```

Nên đặt `aria2c.exe` và `ffmpeg.exe` vào cùng thư mục trước để tải nhanh và video đẹp nhất
(xem [bước 4](#4-tải-aria2c-và-ffmpeg)). File được lưu trong `downloads/nasa/`.

## Cài đặt từng bước

Các bước dưới đây dành cho **Windows**. macOS và Linux cũng dùng được: cài `aria2` và `ffmpeg` bằng
trình quản lý gói (`brew install aria2 ffmpeg`, `sudo apt install aria2 ffmpeg`).

### 1. Cài Python

1. Tải Python 3.10 trở lên tại https://www.python.org/downloads/
2. Chạy file cài đặt, **tick ô "Add python.exe to PATH"** ở cuối màn hình đầu tiên, rồi bấm
   **Install Now**.
3. Kiểm tra: mở **Command Prompt** hoặc **PowerShell**, gõ `python --version`. Kết quả sẽ giống
   `Python 3.13.0`.

### 2. Tải fb-dl về

- **Có Git:** `git clone https://github.com/loooveee/fb-dl.git`
- **Không có Git:** trên trang GitHub bấm **Code** → **Download ZIP**, rồi giải nén.

Sau đó mở cửa sổ lệnh **bên trong thư mục `fb-dl`**. Trong File Explorer, mở thư mục, bấm vào thanh
địa chỉ, gõ `cmd` rồi nhấn Enter.

### 3. Cài các gói Python

```bash
pip install -r requirements.txt
```

### 4. Tải aria2c và ffmpeg

- **aria2c** tải nhiều ảnh cùng lúc, nhanh hơn nhiều.
- **ffmpeg** ghép hình ảnh và âm thanh chất lượng cao nhất thành một file MP4. Không có nó, video sẽ được
  lưu ở chất lượng thấp hơn.

Không có hai công cụ này fb-dl vẫn chạy, chỉ chậm hơn và video chất lượng thấp hơn.

| Công cụ | Tải tại | File cần chép vào thư mục `fb-dl` |
|---|---|---|
| aria2c | https://github.com/aria2/aria2/releases (file zip `win-64bit`) | `aria2c.exe` |
| ffmpeg | https://www.gyan.dev/ffmpeg/builds/ (`ffmpeg-release-essentials.zip`) | `bin\ffmpeg.exe` |

Thư mục của bạn sẽ trông như sau:

```
fb-dl/
├── fb-dl.py
├── aria2c.exe
├── ffmpeg.exe
├── requirements.txt
└── README.md
```

### 5. Trình duyệt

fb-dl dùng **Microsoft Edge** (có sẵn trên mọi máy Windows 10 / 11) hoặc **Google Chrome**. Nếu máy
không có cả hai, chạy:

```bash
python -m playwright install chromium
```

## Đăng nhập

Khi chưa đăng nhập, Facebook chỉ cho xem vài bài, nên hãy đăng nhập một lần:

```bash
python fb-dl.py --login
```

1. Một cửa sổ trình duyệt mở ra ở trang đăng nhập Facebook.
2. Bạn tự đăng nhập trong đó như bình thường (có 2FA cũng được).
3. Cửa sổ tự đóng. Phiên đăng nhập được lưu vào `fb-session.json`.

fb-dl **không bao giờ thấy mật khẩu của bạn**: bạn gõ nó vào chính trang của Facebook, và chỉ cookie
đăng nhập được lưu lại. Kiểm tra:

```bash
python fb-dl.py --check-login
```

```
✓ Đang đăng nhập là N*** T*** B***
```

Tên của bạn được che có chủ ý, để ảnh chụp màn hình cửa sổ lệnh không làm lộ tài khoản.

> [!CAUTION]
> `fb-session.json` có giá trị như mật khẩu: đừng bao giờ chia sẻ. Nên dùng **tài khoản phụ**, vì
> Facebook có thể hạn chế tài khoản cuộn quá nhiều. Xem [Quyền riêng tư và an toàn](#quyền-riêng-tư-và-an-toàn).

**Cách đăng nhập khác:** nếu bạn đã xuất cookie Facebook bằng tiện ích trình duyệt (file `cookies.txt`
dạng Netscape hoặc JSON), dùng `--cookies cookies.txt` thay cho `--login`.

## Tải một trang cá nhân hoặc fanpage

Mở trang đó trên trình duyệt, chép link trên thanh địa chỉ, rồi chạy:

```bash
python fb-dl.py https://www.facebook.com/nasa
```

Vậy là xong. Mặc định fb-dl lưu **tất cả**, từ bài đầu tiên tới hôm nay, chất lượng cao nhất.
Các cách nhập sau đều được:

```bash
python fb-dl.py nasa
python fb-dl.py https://www.facebook.com/nasa
python fb-dl.py https://www.facebook.com/profile.php?id=123456789012345
python fb-dl.py 123456789012345
```

Bạn cũng có thể đưa link một bài, reel hoặc video: `/posts/...`, `/share/p/...`, `/reel/...`,
`/watch?v=...`, `/photo/?fbid=...` hoặc `fb.watch/...`.

**Màn hình khi đang chạy** (ví dụ):

```
━━ nasa ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  NASA - National Aeronautics and Space Administration · 28M followers · id 100044561550831
  Đăng nhập: N*** T*** B***
  Vừa đọc timeline vừa tải → D:\fb-dl\downloads\nasa

  ✓ [1 ảnh] 2026-11-06_1679274853567884_Nice shades. 😎 This structure, called a sunshade,  414.8 KB
  ✓ [1 reel] 2026-11-05_1678344756994227_NASA astronaut Anil Menon and CSA (Canadian Space  5.1 MB
  ⠹ Đang cuộn · thấy 640 bài, tới 2016-03  │  ━━━━━━╸━━━━━━━━━━━━  120/640 đã lưu  │  1.9 GB · 12.4 MB/s  │  0 lỗi
```

fb-dl **vừa đọc vừa tải**: bài nào cuộn tới là được tải ngay ở chế độ nền, không phải đợi cuộn hết
timeline. Dòng ở cuối cho biết đã cuộn tới đâu (`tới 2016-03`), đã thấy bao nhiêu bài và đã lưu được
bao nhiêu. Trang có nhiều năm bài viết có thể mất 20-30 phút để cuộn hết. Khi cuộn tới bài đầu tiên,
dòng này chuyển thành thanh tiến độ bình thường, có phần trăm và thời gian còn lại:

```
  ⠹ ━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━   72%  910/1250 đã lưu  │  3.4 GB · 11.8 MB/s  │  ETA 04:51  │  0 lỗi
```

Sau đó đến story và tab Ảnh / Album, rồi hiện bảng tổng kết:

```
  ━━ Xong ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ 1250 bài, 2 file story, 3400 ảnh từ tab Ảnh / Album   ✗ 0 lỗi · 6.1 GB mới trong 52:10
  Thư mục: D:\fb-dl\downloads\nasa  (posts.csv: 1250)
```

Nếu cửa sổ hẹp, các phần ít quan trọng của dòng này (tốc độ, thời gian còn lại) sẽ được ẩn bớt.

**Ví dụ hay dùng:**

| Lệnh | Tác dụng |
|---|---|
| `python fb-dl.py nasa` | Tất cả (mặc định) |
| `python fb-dl.py nasa -n 50` | Chỉ 50 bài mới nhất |
| `python fb-dl.py nasa --since 2025-01-01` | Chỉ bài từ 01/01/2025 trở đi |
| `python fb-dl.py nasa --since 2025-01-01 --until 2025-06-30` | Chỉ bài trong khoảng đó |
| `python fb-dl.py nasa --update` | Chỉ bài mới kể từ lần chạy trước (nhanh) |
| `python fb-dl.py nasa --no-all-photos` | Bỏ tab Ảnh / Album (nhanh hơn nhiều với trang lớn) |
| `python fb-dl.py nasa --no-videos` | Chỉ chữ và ảnh |
| `python fb-dl.py nasa --metadata-only` | Chỉ danh sách bài (CSV + JSON), không tải file |
| `python fb-dl.py nasa -o D:\Facebook` | Lưu vào chỗ khác |
| `python fb-dl.py trang1 trang2 trang3` | Tải lần lượt nhiều trang |
| `python fb-dl.py nasa --lang en` | Thông báo bằng tiếng Anh |

> [!TIP]
> Trong **PowerShell**, đặt link có `&` hoặc `?` trong dấu nháy:
> `python fb-dl.py "https://www.facebook.com/profile.php?id=123456789012345"`

## Bạn nhận được gì

```
downloads/nasa/
├── posts/        mỗi bài một file .txt: link, ngày, thống kê, nội dung, danh sách file của bài
├── images/       ảnh của các bài (bài nhiều ảnh: ..._01.jpg, ..._02.jpg, ...)
├── videos/       video của các bài
├── reels/        reel
├── stories/      story trong 24 giờ qua
├── photos/       tab Ảnh (mọi ảnh trang đã đăng), tên là <id ảnh>.jpg
├── albums/       tab Album, mỗi album một thư mục
├── metadata/     mỗi bài một file JSON (mọi thông tin fb-dl có về bài đó)
├── posts.csv     tất cả bài trong một bảng, mở bằng Excel
├── stories.json  các story đã lưu
├── profile.json  tên, id, username, số người theo dõi
├── avatar.jpg    ảnh đại diện, kích thước gốc
├── cover.jpg     ảnh bìa, kích thước gốc
├── fb-dl.log     mọi thứ đã hiện trên màn hình, kèm giờ (mỗi lượt chạy được nối thêm vào cuối)
└── failed.txt    chỉ có khi có thứ không tải được, kèm link
```

Mọi file của một bài đều bắt đầu bằng cùng một tên `<ngày>_<id bài>_<đầu nội dung>`, nên dễ ghép file
chữ trong `posts/` với ảnh / video của nó. Ngày của file được đặt theo ngày đăng bài, nên sắp xếp theo
ngày trong File Explorer sẽ thấy các bài đúng thứ tự.

File `.txt` của một bài trông như sau:

```
https://www.facebook.com/nasa/posts/pfbid0iFttxes1ypW77...
2026-11-06 19:55 · NASA - National Aeronautics and Space Administration
Reactions 228 · Comments 9 · Shares 21
Files: ../images/2026-11-06_1679274853567884_Nice shades. 😎 This structure, called a sunshade,.jpg

Nice shades. 😎
This structure, called a sunshade, will fly on ...
```

fb-dl giữ đúng những gì có trên timeline: bài của chủ trang, bài người khác đăng lên tường, bài chủ trang
được gắn thẻ, và bài cộng tác. Nó bỏ qua quảng cáo và bài không liên quan mà Facebook chèn vào
(`--include-others` để giữ lại).

### Cách hoạt động

1. Một cửa sổ Edge / Chrome ẩn mở trang bằng phiên đăng nhập của bạn và cuộn xuống tới bài đầu tiên, giống
   như bạn tự cuộn.
2. Bài nào tìm thấy là được lưu ngay (nội dung + thông tin), ảnh và video của bài được tải ở chế độ nền
   trong lúc vẫn tiếp tục cuộn.
3. Sau đó đến story, rồi đọc tab Ảnh và Album. Ảnh nào bạn đã có (từ bài viết) thì không tải lại.
4. Mọi thứ đã xong được ghi nhớ trong `.progress.db`, nên lần chạy sau chỉ lấy phần còn thiếu.

## Dừng, tải tiếp, cập nhật

- **Dừng bất cứ lúc nào** bằng `Ctrl+C`.
- **Tải tiếp:** chạy lại đúng lệnh cũ. Bài đã tải sẽ được bỏ qua.
- **Lấy bài mới sau này:** thêm `--update`. Nó dừng cuộn ngay khi gặp những bài bạn đã có và bỏ qua tab
  Ảnh / Album, nên chỉ mất khoảng một phút. Thỉnh thoảng chạy không có `--update` để cập nhật cả các tab.
- **Có lỗi?** Lỗi hiện ngay trên màn hình, và được ghi vào `failed.txt`, chia nhóm theo bài đăng, story
  và tab Ảnh / Album. Bài chỉ tải được một phần còn có link tới **từng ảnh hoặc video bị lỗi**, để bạn mở
  đúng ảnh / video đó trên Facebook:
  ```
  == Bài đăng (1) ==
  https://www.facebook.com/nasa/posts/pfbid0abc...
      1/3 ảnh không tải được; 1/1 video không tải được
      - ảnh: https://www.facebook.com/photo/?fbid=1617540283064778   (images/2026-11-06_..._02.jpg)
      - reel: https://www.facebook.com/reel/1056346190744779/   (HTTP Error 403: Forbidden)

  == Tab Ảnh / Album (1) ==
  https://www.facebook.com/photo/?fbid=1586261582859315
      không tải được ảnh: photos/1586261582859315.jpg
  ```
  Chạy lại đúng lệnh cũ để thử lại. `failed.txt` tự biến mất khi mọi thứ đã ổn.
- **Muốn xem lại lượt chạy đã làm gì?** Mở `fb-dl.log` trong thư mục của trang: nó lưu mọi thứ đã hiện
  trên màn hình, kèm giờ, cho mọi lượt chạy. Tên tài khoản của bạn trong đó cũng được che.

## Tất cả tuỳ chọn

Chạy `python fb-dl.py -h` để xem ngay trong cửa sổ lệnh.

**Tải những gì** (mặc định: tất cả)

| Tuỳ chọn | Tác dụng |
|---|---|
| `-n`, `--limit N` | Chỉ N bài mới nhất (và N ảnh đầu của tab Ảnh và của mỗi album) |
| `--since YYYY-MM-DD` | Chỉ bài từ ngày này trở đi (dừng cuộn khi tới đó). Không áp dụng cho tab Ảnh / Album |
| `--until YYYY-MM-DD` | Chỉ bài tới hết ngày này. Không áp dụng cho tab Ảnh / Album |
| `--update` | Dừng cuộn khi gặp 10 bài liên tiếp bạn đã có, và bỏ qua tab Ảnh / Album |
| `--no-photos` | Không tải ảnh nào (cũng bỏ tab Ảnh / Album, avatar và ảnh bìa) |
| `--no-videos` | Không tải video và reel |
| `--no-text` | Không ghi file `.txt` |
| `--no-stories` | Không tải story |
| `--no-all-photos` | Bỏ tab Ảnh và Album (chỉ lưu ảnh của các bài đăng) |
| `--metadata-only` | Chỉ `posts.csv` và `metadata/`, không tải file |
| `--include-others` | Giữ cả quảng cáo và bài không liên quan chèn vào timeline |
| `--raw` | Lưu thêm dữ liệu gốc của Facebook vào `metadata/*.json` (đã xoá thông tin tài khoản của bạn) |
| `-o`, `--output THƯ_MỤC` | Nơi lưu (mặc định: `downloads`) |

**Chất lượng và tốc độ**

| Tuỳ chọn | Tác dụng |
|---|---|
| `--fast-photos` | Chỉ lấy ảnh hiện trên timeline: nhanh hơn, nhưng album lớn bị thiếu |
| `--direct-video` | Tải link MP4 trên timeline thay vì dùng yt-dlp (nhanh hơn, thường chỉ 720p) |
| `-j`, `--jobs N` | Số file tải cùng lúc (mặc định: 16) |
| `-x`, `--connections N` | Số kết nối mỗi file (mặc định: 8) |
| `--video-jobs N` | Số video tải cùng lúc (mặc định: 3) |
| `-w`, `--workers N` | Số luồng đọc trang ảnh (mặc định: 4) |
| `--wait GIÂY` | Nghỉ giữa các lần mở trang ảnh (mặc định: 0.5) |
| `--batch N` | Số bài mỗi lô tải (mặc định: 30) |

**Trình duyệt và cuộn trang**

| Tuỳ chọn | Tác dụng |
|---|---|
| `--browser auto\|msedge\|chrome\|chromium` | Trình duyệt dùng để đọc timeline (mặc định: Edge, rồi Chrome, rồi Chromium) |
| `--show-browser` | Hiện cửa sổ trình duyệt khi cuộn |
| `--scroll-wait GIÂY` | Nghỉ giữa mỗi lần cuộn (mặc định: 1.5) |
| `--max-idle N` | Dừng sau N lần cuộn không có bài mới (mặc định: 25) |

**Đăng nhập**

| Tuỳ chọn | Tác dụng |
|---|---|
| `--login` | Đăng nhập trong cửa sổ trình duyệt và lưu phiên |
| `--check-login` | Kiểm tra phiên đã lưu còn dùng được không |
| `--logout` | Xoá phiên đã lưu |
| `--cookies FILE` | Dùng file cookie xuất từ trình duyệt thay cho phiên đã lưu |
| `--no-login` | Không dùng phiên đã lưu |

**Hiển thị**

| Tuỳ chọn | Tác dụng |
|---|---|
| `--lang en\|vi` | Ngôn ngữ thông báo (mặc định: theo ngôn ngữ máy) |
| `--no-color` | Chữ trơn, không màu (hoặc đặt `NO_COLOR=1`) |
| `-V`, `--version` | Xem phiên bản |

## Quyền riêng tư và an toàn

- **`fb-session.json` có giá trị như mật khẩu.** Không bao giờ chia sẻ, tải lên mạng hay gửi cho ai.
  File đã nằm trong `.gitignore` nên Git không bao giờ đưa lên. Nếu nén thư mục `fb-dl` để gửi người khác,
  hãy bỏ file này ra.
- **Nên dùng tài khoản phụ.** Facebook có thể yêu cầu xác minh hoặc hạn chế tài khoản cuộn quá nhiều.
- **Tài khoản của bạn được giữ kín.** Màn hình chỉ hiện tên đã che (`N*** T*** B***`) và không bao giờ
  hiện id. Tài khoản của bạn không được ghi vào bất kỳ file kết quả nào: nếu timeline có bài bạn viết hoặc
  được gắn thẻ, tác giả được lưu là `(bạn)`. `--raw` cũng xoá id và tên của bạn khỏi dữ liệu gốc của
  Facebook (các nội dung khác, như bình luận có nhắc tới bạn, được giữ nguyên).
- **Cookie chỉ nằm trong bộ nhớ.** Ngoài `fb-session.json`, fb-dl không bao giờ ghi cookie của bạn ra
  file nào khác và không đặt nó lên dòng lệnh.
- **Story:** fb-dl chỉ mở trang story để đọc. Nó không bấm "xem" và không chuyển sang story của người
  khác, nên chỉ lưu story của đúng trang bạn yêu cầu. Facebook vẫn có thể ghi nhận một lượt truy cập.
- **Trang cá nhân riêng tư:** chỉ lấy được những gì tài khoản của bạn được phép xem. Hãy tôn trọng
  quyền riêng tư của người khác.

## Đăng xuất và xoá dữ liệu

**1. Xoá phiên đã lưu**

```bash
python fb-dl.py --logout
```

Lệnh này xoá `fb-session.json`. Không còn chỗ nào khác giữ phiên đăng nhập: mỗi lần chạy, fb-dl dùng một
hồ sơ trình duyệt mới và trống, và không ghi cookie của bạn ra nơi nào khác.

**2. Đăng xuất phiên đó trên Facebook**

Xoá file không đăng xuất phiên ở phía Facebook. Để làm việc đó:

1. Trên Facebook, mở **Cài đặt & quyền riêng tư** → **Cài đặt** → **Trung tâm tài khoản**
2. **Mật khẩu và bảo mật** → **Nơi bạn đã đăng nhập**
3. Chọn phiên fb-dl đã dùng (máy Windows với Edge / Chrome, vào lúc bạn chạy `--login`) và bấm
   **Đăng xuất**

Đổi mật khẩu Facebook sẽ đăng xuất mọi phiên cùng lúc.

**3. Xoá file cookie đã xuất**

Nếu đã dùng `--cookies`, hãy xoá cả file `cookies.txt` / JSON đó.

**4. Xoá dữ liệu đã tải và các gói thư viện (tuỳ chọn)**

- Thư mục kết quả (mặc định `downloads/`). Thư mục của mỗi trang còn có file ẩn `.progress.db` ghi nhớ
  những gì đã tải.
- Các gói thư viện:
  ```bash
  pip uninstall playwright yt-dlp imageio-ffmpeg
  ```

## Lỗi thường gặp và câu hỏi

**Chỉ tìm thấy vài bài.**
Bạn chưa đăng nhập, hoặc phiên đã hết hạn. Chạy `python fb-dl.py --check-login`, rồi chạy lại
`--login` nếu cần.

**"Facebook yêu cầu xác minh tài khoản".**
Mở facebook.com trên trình duyệt thường của bạn, xác minh xong rồi chạy lại `--login`.

**Dừng cuộn trước khi tới các bài cũ nhất.**
Facebook tải chậm. Chạy lại với `--scroll-wait 3 --max-idle 50`. Bài đã có sẽ được bỏ qua. Thêm
`--show-browser` để xem nó đang làm gì.

**Chạy rất lâu.**
Trang lớn có hàng nghìn bài, và tab Ảnh / Album cũng phải cuộn từng trang. Dùng `--no-all-photos` để bỏ
tab đó, hoặc `--since` để dừng ở một ngày. Bạn có thể dừng bằng `Ctrl+C` và tải tiếp sau.

**Một số video bị lỗi.**
Cập nhật yt-dlp (`pip install -U yt-dlp`) rồi chạy lại, hoặc thử `--direct-video`.

**Video không phát được.**
Facebook thường gửi video AV1. Dùng VLC, trình duyệt mới, hoặc ứng dụng Windows Media Player.

**Cùng một ảnh có trong `images/` và `photos/`.**
`images/` là ảnh của các bài, `photos/` là toàn bộ tab Ảnh, `albums/` là các album, nên có trùng. Mỗi ảnh
chỉ được tải một lần: các bản còn lại là hard link tới cùng một file, nên không tốn thêm dung lượng (với ổ
không hỗ trợ hard link như USB định dạng FAT32 / exFAT thì là bản sao thật). Dùng `--no-all-photos` nếu chỉ
cần bài đăng.

**"Bỏ qua N bài quảng cáo / bài của trang khác".**
Đó là quảng cáo hoặc bài không liên quan tới trang. Thêm `--include-others` nếu vẫn muốn giữ.

**"Không mở được trình duyệt".**
Cài Edge hoặc Chrome, hoặc chạy `python -m playwright install chromium`.

**Báo `python` is not recognized.**
Python chưa có trong PATH. Cài lại và tick **"Add python.exe to PATH"**, hoặc dùng `py` thay cho
`python`.

**Báo `pip` is not recognized.**
Dùng `python -m pip install -r requirements.txt` thay thế (hoặc `py -m pip ...`).

**Có tải được nhóm (group) không?**
Không, chỉ trang cá nhân và fanpage (cùng các bài lẻ ở bất kỳ đâu).

**Cập nhật chính fb-dl bằng cách nào?**

- **Có Git:** chạy `git pull` trong thư mục `fb-dl`, rồi `pip install -U -r requirements.txt`.
- **Không có Git:** tải lại file ZIP và chép file `fb-dl.py` mới đè lên file cũ. Giữ nguyên
  `fb-session.json`, `aria2c.exe` và `ffmpeg.exe` của bạn.

Nếu video bắt đầu bị lỗi, hãy cập nhật yt-dlp trước: `pip install -U yt-dlp`.

## Miễn trừ trách nhiệm

**Dự án chỉ dành cho mục đích học tập.** Bạn tự chịu trách nhiệm về cách sử dụng.
Hãy tôn trọng bản quyền của tác giả, quyền riêng tư của người khác và Điều khoản dịch vụ của Facebook.

Dự án không liên quan tới Facebook hay Meta. Tác giả không chịu trách nhiệm cho việc sử dụng sai mục đích.

## Giấy phép

MIT © loooveee
