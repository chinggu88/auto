import 'dart:developer';
import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter_challenge/model/carddata.dart';
import 'package:get/get.dart';
import 'package:intl/intl.dart';

class Main_Controller extends GetxController {
  static Main_Controller get to => Get.find();
  final _now = DateTime.now().obs;

  ///오늘날짜
  DateTime get now => _now.value;
  set now(DateTime value) => _now.value = value;

  final _remaindDays = <int>[].obs;

  ///상단 스케줄 날짜
  List<int> get remaindDays => _remaindDays;
  set remaindDays(List<int> value) => _remaindDays.addAll(value);

  final _cardDataList = <CardData>[].obs;

  ///카드데이터
  List<CardData> get cardDataList => _cardDataList;
  set cardDataList(List<CardData> value) => _cardDataList.addAll(value);
  @override
  void onReady() {
    // TODO: implement onReady
    super.onReady();
    remainday();
    setCardData();
  }

  ///DateTime.now() -> tuesday 11
  String dateTimeToday() {
    String dayName = DateFormat('EEEE').format(DateTime.now());
    Map<String, String> days = {
      "Monday": "월",
      "Tuesday": "화",
      "Wednesday": "수",
      "Thursday": "목",
      "Friday": "금",
      "Saturday": "토",
      "Sunday": "일"
    };
    String output = "${dayName.toUpperCase()} ${DateTime.now().day}";
    return output;
  }

  void remainday() {
    List<int> days = [];
    bool contine = true;
    int addday = 1;
    int monthnow = DateTime.now().month;
    while (contine) {
      if (monthnow == DateTime.now().add(Duration(days: addday)).month) {
        days.add((DateTime.now().add(Duration(days: addday)).day));
        addday++;
      } else {
        contine = false;
      }
    }
    remaindDays = days;
  }

  void setCardData() {
    cardDataList.add(
      CardData(
          startTime: '09:10:00',
          endTime: '10:10:00',
          subject: 'DESING METTING',
          member: ['lee', 'kim', 'park', 'oh'],
          cardColor: Colors.blueAccent),
    );
    cardDataList.add(
      CardData(
          startTime: '10:20:00',
          endTime: '13:20:00',
          subject: 'DALIY PROJECT',
          member: ['lee', 'kim', 'oh'],
          cardColor: Colors.orange),
    );
    cardDataList.add(
      CardData(
          startTime: '13:30:00',
          endTime: '14:30:00',
          subject: 'WEEKLY PROJECT',
          member: ['jone', 'jeik', 'june', 'oh'],
          cardColor: Colors.greenAccent),
    );
    cardDataList.add(
      CardData(
          startTime: '14:40:00',
          endTime: '16:10:00',
          subject: 'MONTHLY METTING',
          member: ['ME', 'William', 'Sophia', 'Benjamin', 'Olivia'],
          cardColor: Colors.yellowAccent),
    );
    cardDataList.add(
      CardData(
          startTime: '17:00:00',
          endTime: '22:10:00',
          subject: 'DINING METTING',
          member: ['lee', 'kim', 'park', 'oh'],
          cardColor: Colors.cyanAccent),
    );
  }
}
