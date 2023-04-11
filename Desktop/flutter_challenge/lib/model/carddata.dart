import 'dart:ui';

class CardData {
  String? startTime;
  String? endTime;
  String? subject;
  List<String>? member;
  Color? cardColor;

  CardData(
      {this.startTime,
      this.endTime,
      this.subject,
      this.member,
      this.cardColor});

  CardData.fromJson(Map<String, dynamic> json) {
    startTime = json['startTime'];
    endTime = json['endTime'];
    subject = json['subject'];
    member = json['member'];
    cardColor = json['cardColor'];
  }
}
