# RTL-SDR + readsb + Flightradar24 feeder on one Pi

One RTL-SDR dongle can only be opened by **one** program. The trick is to let `readsb` own the dongle and
re-publish the decoded stream on the network; `fr24feed` and our dashboard both consume it from there.

```
RTL-SDR ──► readsb ──┬─► /run/readsb/aircraft.json   ──► Plane Tracker (this project)
 (1090 MHz)          └─► Beast TCP 127.0.0.1:30005   ──► fr24feed ──► Flightradar24
```

## 1. Antenna / dongle
* Use a 1090 MHz antenna (or a short 1090 collinear) with a clear sky view; a filtered LNA (e.g. FlightAware
  Pro Stick Plus / a 1090 SAW filter) helps a lot.
* Check the dongle is seen: `lsusb | grep -i rtl` (RTL2838 / RTL2832U).
* Blacklist the TV driver if needed: `echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/blacklist-rtl.conf`.

## 2. readsb (decoder)
```bash
sudo bash -c "$(wget -nv -O - https://github.com/wiedehopf/adsb-scripts/raw/master/readsb-install.sh)"
sudo readsb-set-location 51.5074 -0.1278      # your lat lon
sudo readsb-gain auto-verbose                 # or a fixed gain once tuned
```
Check `/etc/default/readsb` contains (defaults usually do):
```
RECEIVER_OPTIONS="--device 0 --device-type rtlsdr --gain auto-verbose --ppm 0"
DECODER_OPTIONS="--max-range 450 --write-json-every 1"
NET_OPTIONS="--net --net-heartbeat 60 --net-ro-size 1250 --net-ro-interval 0.05 --net-ro-port 30002 --net-bi-port 30004,30104 --net-bo-port 30005 --net-sbs-port 30003"
JSON_OPTIONS="--json-location-accuracy 2 --range-outline-hours 24"
```
`--write-json-every 1` gives the 1-second refresh the dashboard wants. Restart: `sudo systemctl restart readsb`.

Verify: `cat /run/readsb/aircraft.json | head -c 400` shows `"aircraft":[...]`.

### Telling the dashboard where it is
In **Settings → Local SDR URL / file** use either:
* `/run/readsb/aircraft.json` (file, simplest, no web server needed) – **default for this guide**, or
* `http://localhost:8080/data/aircraft.json` – if you front readsb with tar1090/lighttpd or your own server
  on port 8080 (`sudo bash -c "$(wget -nv -O - https://github.com/wiedehopf/tar1090/raw/master/install.sh)"`
  then change lighttpd's port, the URL becomes `…:8080/tar1090/data/aircraft.json`).

dump1090-fa / dump1090-mutability work the same way: point at their `aircraft.json` and give fr24feed the
Beast port they expose (30005 for dump1090-fa; mutability needs `--net-bo-port 30005`).

## 3. fr24feed (Flightradar24)
```bash
sudo bash -c "$(wget -O - https://repo-feed.flightradar24.com/install_fr24_rpi.sh)"
sudo fr24feed --signup
```
Answer the wizard:
| Question | Answer |
|---|---|
| Email / existing sharing key | your FR24 account (or leave key blank for a new one) |
| Receiver type | **ModeS Beast (USB/network)**  →  `receiver="beast-tcp"` |
| Host:port | `127.0.0.1:30005` |
| MLAT | `no` (needs an extra position source setup; optional) |
| Raw/BS feeds | `no` |

Resulting `/etc/fr24feed.ini` essentials:
```
receiver="beast-tcp"
host="127.0.0.1:30005"
fr24key="YOUR_KEY"
bs="no"
raw="no"
mlat="no"
mlat-without-gps="no"
```
```bash
sudo systemctl enable --now fr24feed
fr24feed-status            # or open http://localhost:8754
```
Because fr24feed reads readsb's Beast output instead of the USB stick, **there is no dongle conflict** and
the dashboard works even when FR24 is down. FR24 grants free Business-plan access to active feeders
under their current terms – check your account page after the feeder shows "connected".

## 4. Optional: a second dongle
Only useful for a second band (e.g. 978 MHz UAT in the US) or a second 1090 antenna/location.
```bash
rtl_eeprom -d 0 -s 00001090     # give each stick a unique serial, unplug/replug
rtl_eeprom -d 1 -s 00000978
```
Select by serial in `RECEIVER_OPTIONS="--device 00001090 …"`. For 978 run `dump978-fa` and point a second
readsb/`--net-connector` at it; do not share one serial between two programs.

## 5. Startup order & health
`plane-tracker.service` starts after `readsb.service` and retries every second, so order does not matter.
If the SDR stops the dashboard shows **NO DATA FEED**; with data source *Auto* or *Hybrid* it falls back to
adsb.lol automatically.

```bash
systemctl status readsb fr24feed plane-tracker
journalctl -u plane-tracker -f
curl -s localhost:5000/api/health
```
