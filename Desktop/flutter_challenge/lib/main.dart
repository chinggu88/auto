import 'package:flutter/material.dart';
import 'package:flutter_challenge/controller/main_controller.dart';
import 'package:flutter_challenge/view/challenge.dart';
import 'package:get/get.dart';

void main() {
  runApp(GetMaterialApp(
    initialRoute: '/main',
    getPages: [
      GetPage(
          name: '/main',
          page: () => Mainview(),
          binding: BindingsBuilder(() {
            Get.put(Main_Controller());
          })),
    ],
  ));
}
