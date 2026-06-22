#!/bin/bash
sleep 1
systemctl stop hostapd
cp /etc/dhcpcd.conf.wifi /etc/dhcpcd.conf
systemctl restart dhcpcd
sleep 5
#wpa_cli -i wlan0 reconnect
sleep 20
iw dev wlan0 set power_save off
#/usr/bin/python3 /home/Javo/Proyects/boot_menu/boot_menu.py &
su - Javo -s /bin/bash -c "python3 /home/Javo/Proyects/boot_menu/boot_menu.py >> /tmp/bootmenu_hotspot.log 2>&1" &
#iwconfig wlan0 power off
