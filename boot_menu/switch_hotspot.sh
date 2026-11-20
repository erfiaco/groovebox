#!/bin/bash
sleep 1
systemctl stop hostapd
#wpa_cli -i wlan0 disconnect
cp /etc/dhcpcd.conf.hotspot /etc/dhcpcd.conf
systemctl restart dhcpcd
sleep 4
systemctl start hostapd
sleep 3
#/usr/bin/python3 /home/Javo/Proyects/boot_menu/boot_menu.py &
su -l Javo -c "python3 /home/Javo/Proyects/boot_menu/boot_menu.py" &
