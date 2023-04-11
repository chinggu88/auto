import 'package:flutter/material.dart';
import 'package:flutter_challenge/controller/main_controller.dart';
import 'package:get/get.dart';

class Mainview extends GetView<Main_Controller> {
  const Mainview({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        actions: [
          ClipOval(
              child: Image.network(
            "https://mobile.busan.com/nas/wcms/wcms_data/photos/2023/01/30/2023013014564053484_l.jpg",
            fit: BoxFit.fill,
            width: 60,
            height: 60,
          )),
          SizedBox(
            width: Get.size.width * 0.7,
          ),
          Icon(
            Icons.add,
            size: 30,
          ),
          SizedBox(
            width: Get.size.width * 0.05,
          ),
        ],
        backgroundColor: Colors.blueGrey[900],
        elevation: 0.0,
      ),
      backgroundColor: Colors.blueGrey[900],
      body: Padding(
        padding: const EdgeInsets.only(left: 20, right: 20, top: 20),
        child: SizedBox(
          height: Get.size.height,
          child: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${controller.dateTimeToday()}',
                  style: const TextStyle(
                      color: Colors.white,
                      fontSize: 20,
                      fontWeight: FontWeight.bold),
                ),
                SizedBox(
                  width: Get.size.width,
                  height: 70,
                  child: SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    child: scheduleDays(),
                  ),
                ),
                Cardwidget()
                // Container(
                //   height: 200,
                //   width: Get.size.width,
                //   decoration: BoxDecoration(
                //     color: Colors.orange,
                //     borderRadius: BorderRadius.circular(50),
                //   ),
                // )
              ],
            ),
          ),
        ),
      ),
    );
  }

  ///상단 날짜 위젯
  Obx scheduleDays() {
    List<Widget> days = [];
    return Obx(() {
      days.clear();
      days.add(
        const Text(
          'TODAY',
          style: TextStyle(
              color: Colors.white, fontSize: 50, fontWeight: FontWeight.bold),
        ),
      );
      days.add(
        const SizedBox(
          width: 10,
        ),
      );
      days.add(
        CircleAvatar(
          backgroundColor: Colors.pinkAccent,
          radius: 5,
        ),
      );
      days.add(
        const SizedBox(
          width: 10,
        ),
      );
      controller.remaindDays.forEach((e) {
        days.add(
          Text(
            '$e',
            style: TextStyle(
              color: Colors.white,
              fontSize: 50,
            ),
          ),
        );
        days.add(const SizedBox(
          width: 15,
        ));
      });
      return Row(
        children: days,
      );
    });
  }

  Obx Cardwidget() {
    List<Widget> wigets = [];
    return Obx(() {
      controller.cardDataList.length;
      controller.cardDataList.forEach(
        (e) {
          wigets.add(Container(
            height: 200,
            width: Get.size.width,
            decoration: BoxDecoration(
              color: e.cardColor,
              borderRadius: BorderRadius.circular(50),
            ),
            child: Column(
              children: [
                Row(
                  children: [
                    //시간 부분
                    Container(
                      alignment: Alignment.center,
                      width: (Get.size.width - 40) * 0.3,
                      height: 200,
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Text(
                            '${e.startTime!.substring(0, 2)}',
                            style: TextStyle(fontSize: 30),
                          ),
                          Text(
                            '${e.startTime!.substring(3, 5)}',
                            style: TextStyle(fontSize: 20),
                          ),
                          Container(
                            width: 1,
                            height: 40,
                            color: Colors.black,
                          ),
                          Text(
                            '${e.endTime!.substring(0, 2)}',
                            style: TextStyle(fontSize: 30),
                          ),
                          Text(
                            '${e.endTime!.substring(3, 5)}',
                            style: TextStyle(fontSize: 20),
                          )
                        ],
                      ),
                    ),
                    //미팅주제
                    Container(
                      alignment: Alignment.center,
                      width: (Get.size.width - 40) * 0.7,
                      height: 200,
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Text(
                            '${e.subject}',
                            style: const TextStyle(
                                fontSize: 50, fontWeight: FontWeight.bold),
                          ),
                          Row(
                            children: List<Widget>.generate(
                                e.member!.length < 4 ? e.member!.length : 4,
                                (index) {
                              return index < 3
                                  ? Text(
                                      '${e.member![index]} ',
                                      style: TextStyle(
                                          fontSize: 20,
                                          color: e.member![index] == 'ME'
                                              ? Colors.black
                                              : Colors.grey),
                                    )
                                  : Text(
                                      '+${e.member!.length - 3}',
                                      style: const TextStyle(
                                        fontSize: 20,
                                      ),
                                    );
                            }),
                          )
                        ],
                      ),
                    )
                  ],
                )
              ],
            ),
          ));
          wigets.add(SizedBox(
            height: 10,
          ));
        },
      );
      return Column(
        children: wigets,
      );
    });
  }
}
